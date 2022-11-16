import numpy as np
import torch
from torch.nn import Module, ModuleList, Embedding, Linear, TransformerEncoderLayer, CrossEntropyLoss, LayerNorm, Dropout


class EmbeddingProductHead(Module):

    def __init__(self, hidden_dim=256, num_features=3, num_bins=(41, 41, 41)):
        super(EmbeddingProductHead, self).__init__()
        assert num_features == 3
        self.num_features = num_features
        self.num_bins = num_bins
        self.hidden_dim = hidden_dim
        self.combined_bins = int(np.sum(num_bins))
        self.linear = Linear(hidden_dim, self.combined_bins * hidden_dim)
        self.act = torch.nn.Softplus()
        self.logit_scale = torch.nn.Parameter(torch.tensor(1.0))

    def forward(self, emb):
        batch_size, seq_len, _ = emb.shape
        bin_emb = self.act(self.linear(emb))
        bin_emb = bin_emb.view(batch_size, seq_len, self.combined_bins, self.hidden_dim)
        bin_emb_x, bin_emb_y, bin_emb_z = torch.split(bin_emb, self.num_bins, dim=2)

        bin_emb_xy = bin_emb_x.unsqueeze(2) * bin_emb_y.unsqueeze(3)
        bin_emb_xy = bin_emb_xy.view(batch_size, seq_len, -1, self.hidden_dim)

        logits = bin_emb_xy @ bin_emb_z.transpose(2, 3)
        logits = self.logit_scale.exp() * logits.view(batch_size, seq_len, -1)
        return logits


class JetTransformer(Module):
    def __init__(self,
                hidden_dim=256,
                num_layers=10,
                num_heads=4,
                num_features=3,
                num_bins=(41, 41, 41),
                dropout=0.1,
                output='linear',
                classifier=False):
        super(JetTransformer, self).__init__()
        self.num_features = num_features
        self.dropout = dropout
        self.total_bins = int(np.prod(num_bins))
        self.classifier = classifier
        print(f'Bins: {self.total_bins}')

        # learn embedding for each bin of each feature dim
        self.feature_embeddings = ModuleList([
            Embedding(
                embedding_dim=hidden_dim,
                num_embeddings=num_bins[l]
            ) for l in range(num_features)
        ])

        # build transformer layers
        self.layers = ModuleList([
            TransformerEncoderLayer(
                d_model=hidden_dim,
                nhead=num_heads,
                dim_feedforward=hidden_dim,
                batch_first=True,
                norm_first=True,
                dropout=dropout,
            ) for l in range(num_layers)
        ])

        self.out_norm = LayerNorm(hidden_dim)
        self.dropout = Dropout(dropout)

        # output projection and loss criterion
        if classifier:
            self.flat = torch.nn.Flatten()
            self.out = Linear(hidden_dim*20, 1)
            self.criterion = torch.nn.functional.binary_cross_entropy_with_logits
        else:
            if output == 'linear':
                self.out_proj = Linear(hidden_dim, self.total_bins)
            else:
                self.out_proj = EmbeddingProductHead(hidden_dim, num_features, num_bins)
            self.criterion = CrossEntropyLoss()

    def forward(self, x, padding_mask):

        # construct causal mask to restrict attention to preceding elements
        seq_len = x.shape[1]
        seq_idx = torch.arange(seq_len, dtype=torch.long, device=x.device)
        causal_mask = seq_idx.view(-1, 1) < seq_idx.view(1, -1)
        padding_mask = ~padding_mask

        # project x to initial embedding
        x[x < 0] = 0
        emb = self.feature_embeddings[0](x[:, :, 0])
        for i in range(1, self.num_features):
            emb += self.feature_embeddings[i](x[:, :, i])

        # apply transformer layer
        for layer in self.layers:
            emb = layer(src=emb, src_mask=causal_mask, src_key_padding_mask=padding_mask)
        emb = self.out_norm(emb)
        emb = self.dropout(emb)

        # project final embedding to logits (not normalized with softmax)
        if False:  #self.classifier:
            emb = self.flat(emb)
            out = self.out(emb)
            return out
        else:
            logits = self.out_proj(emb)
            return logits

    def loss(self, logits, true_bin):
        if True:  #not self.classifier:
            # ignore final logits
            logits = logits[:, :-1].reshape(-1, self.total_bins)

            # shift target bins to right
            true_bin = true_bin[:, 1:].flatten()

        loss = self.criterion(logits, true_bin)
        return loss

    def loss_pC(self, logits, true_bin):
        logits = logits[:, :-1].reshape(-1, self.total_bins)

        # shift target bins to right
        true_bin = true_bin[:, 1:].flatten()

        loss = torch.nn.CrossEntropyLoss(reduction='none')(logits, true_bin)
        return loss

    def probability(self, logits, padding_mask, true_bin, perplexity=False, logarithmic=False):
        batch_size, padded_seq_len, num_bin = logits.shape
        seq_len = padding_mask.long().sum(dim=1)

        # ignore final logits
        logits = logits[:, :-1].reshape(-1, self.total_bins)
        probs = torch.softmax(logits, dim=1)

        # shift target bins to right
        true_bin = true_bin[:, 1:].flatten()

        # select probs of true bins
        sel_idx = torch.arange(probs.shape[0], dtype=torch.long, device=probs.device)
        probs = probs[sel_idx, true_bin].view(batch_size, padded_seq_len-1)
        probs[~padding_mask[:, :-1]] = 1.0

        if perplexity:
            probs = probs ** (1 / seq_len.float().view(-1, 1))

        if logarithmic:
            probs = torch.log(probs).sum(dim=1)
        else:
            probs = probs.prod(dim=1)
        return probs

    def sample(self, starts):
        jets = -torch.empty((len(starts), 20, 3), dtype=torch.long, device='cuda')
        true_bins = torch.zeros((len(starts), 20), dtype=torch.long, device='cuda')
        self.eval()
        with torch.no_grad():
            for jet_idx in range(len(starts)):
                # Set first particle to one of the true jets
                current_jet = - torch.ones((1, 20, 3), dtype=torch.long, device='cuda')
                current_jet[:, 0] = starts[jet_idx]

                # Set padding to ignore all particles not generated yet
                padding_mask = current_jet[:, :, 0] != -1
                padding_mask.to('cuda')

                for particle in range(19):
                    # Get probability predictions
                    preds = self.forward(current_jet, padding_mask)
                    preds = torch.nn.functional.softmax(preds[:, :-1], dim=-1)
                    rand = torch.rand((1,), device='cuda')

                    # Sample the bin by checking the cumsum to be larger than random value
                    preds_cum = torch.cumsum(preds[0, particle], dim=-1)
                    idx = torch.searchsorted(preds_cum, rand,)
                    true_bins[jet_idx, particle+1] = idx
                    bins = self.idx_to_bins(idx)

                    for ind, tmp_bin in enumerate(bins):
                        current_jet[0, particle+1, ind] = tmp_bin

                    # Update padding
                    padding_mask = current_jet[:, :, 0] != -1


                jets[jet_idx] = current_jet[0]
        return jets, true_bins

    def idx_to_bins(self, x):
        pT = x % 41
        eta = torch.div((x - pT), 41, rounding_mode='trunc') % torch.div(1271, 41, rounding_mode='trunc')
        phi = torch.div((x - pT - 41 * eta), 1271, rounding_mode='trunc')
        return pT, eta, phi


class CNNclass(Module):
    def __init__(self,):
        super().__init__()
        self.model = torch.nn.Sequential(
            #Input = 1 x 30 x 30, Output = 32 x 30 x 30
            torch.nn.Conv2d(in_channels = 1, out_channels = 32, kernel_size = 3, padding = 1),
            torch.nn.PReLU(),
            #Input = 32 x 30 x 30, Output = 32 x 15 x 15
            torch.nn.MaxPool2d(kernel_size=2),

            #Input = 32 x 15 x 15, Output = 64 x 15 x 15
            torch.nn.Conv2d(in_channels = 32, out_channels = 64, kernel_size = 3, padding = 1),
            torch.nn.PReLU(),
            #Input = 64 x 15 x 15, Output = 64 x 7 x 7
            torch.nn.MaxPool2d(kernel_size=2),

            #Input = 64 x 7 x 7, Output = 64 x 7 x 7
            torch.nn.Conv2d(in_channels = 64, out_channels = 64, kernel_size = 3, padding = 1),
            torch.nn.PReLU(),
            #Input = 64 x 7 x 7, Output = 64 x 3 x 3
            torch.nn.MaxPool2d(kernel_size=2),

            torch.nn.Flatten(),
            torch.nn.Linear(64*3*3, 512),
            torch.nn.PReLU(),
            torch.nn.Linear(512, 1)
        )


    def forward(self, x):
        return self.model(x)

    def loss(self, x, y):
        return torch.nn.functional.binary_cross_entropy_with_logits(x, y)

