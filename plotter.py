import os
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import roc_auc_score, roc_curve

size = 12
FIGSIZE = (4,8/3)
plt.rc('font', size=10)
plt.rc('axes', titlesize=size*1.2)
plt.rc('axes', labelsize=size*1.2)
plt.rc('xtick', labelsize=size*0.9)
plt.rc('ytick', labelsize=size*0.9)
plt.rc('legend', fontsize=size)

def plot_scores(dir):
    fig, ax = plt.subplots(2, 1, sharex=True, constrained_layout=True)
    fig1, ax1 = plt.subplots(2, 1, sharex=True, constrained_layout=True)

    kind = 'perp'
    print(kind)
    data = np.load(os.path.join('models', dir+'_qcd', f'predictions_{kind}.npz'))
    scores = data['scores']
    labels = data['labels']
    upper = np.quantile(scores, 0.995)
    lower = np.quantile(scores, 0.005)
    idx = np.random.permutation(len(scores))
    scores = scores[idx]
    labels = labels[idx]

    ax[0].hist(scores[labels==0],
               density=True, bins=50, histtype='step', range=[lower, upper],
               label='QCD')
    ax[0].hist(scores[labels==1],
               density=True, bins=50, histtype='step', range=[lower, upper],
               label='Top')
    ax[0].set_xlim(lower, upper)
    ax[0].legend()
    ax[0].set_title(f'Trained on QCD')

    meds_qcd = []
    meds_top = []
    for i in range(1, 101):
        nParts = data['nparts'][idx]==i
        meds_qcd.append(np.median(scores[nParts][labels[nParts]==0]))
        meds_top.append(np.median(scores[nParts][labels[nParts]==1]))

    ax1[0].scatter(data['nparts'][idx],scores,
                   c=labels, s=1, alpha=0.1,)
    ax1[0].plot(np.arange(1,101), np.array(meds_qcd), label='QCD')
    ax1[0].plot(np.arange(1,101), np.array(meds_top), label='Top')
    ax1[0].set_ylim(lower, upper)
    ax1[0].set_ylabel('Score')
    ax1[0].set_title(f'Trained on QCD')
    ax1[0].legend(loc='upper right')

    data = np.load(os.path.join('models', dir+'_top', f'predictions_{kind}.npz'))
    scores = data['scores']
    labels = data['labels']
    idx = np.random.permutation(len(scores))
    scores = scores[idx]
    labels = labels[idx]
    ax[1].hist(scores[labels==1],
               density=True, bins=50, histtype='step', range=[lower, upper],
               label='QCD')
    ax[1].hist(scores[labels==0],
               density=True, bins=50, histtype='step', range=[lower, upper],
               label='Top')
    ax[1].set_xlabel('score')
    ax[1].set_title('Trained on top')

    meds_qcd = []
    meds_top = []
    for i in range(1, 101):
        nParts = data['nparts'][idx]==i
        meds_qcd.append(np.median(scores[nParts][labels[nParts]==1]))
        meds_top.append(np.median(scores[nParts][labels[nParts]==0]))

    ax1[1].scatter(data['nparts'][idx], scores,
                   c=np.abs(labels-1), s=1, alpha=0.1,)
    ax1[1].plot(np.arange(1,101), np.array(meds_qcd))
    ax1[1].plot(np.arange(1,101), np.array(meds_top))
    ax1[1].set_title('Trained on top')
    ax1[1].set_ylim(lower, upper)
    ax1[1].set_ylabel('Score')
    ax1[1].set_xlabel('Number of particles')

    fig.savefig(f'scores_{kind}.png',)
    fig1.savefig(f'nParts_score_{kind}.png',)


def plot_rocs():
    fig, ax = plt.subplots(constrained_layout=True)
    score_kinds = ['perp']
    for score_kind in score_kinds:
        data = np.load(f'models/N600k_E100_nC100_nBin30_LRcos_qcd/predictions_{score_kind}.npz')
        scores = data['scores']
        labels = data['labels']
        fpr, tpr, _ = roc_curve(y_true=labels, y_score=-scores)

        ax.plot(tpr, 1. / fpr,
            label=f'QCD {roc_auc_score(labels, -scores):.3f}')

        data = np.load(f'models/N600k_E100_nC100_nBin30_LRcos_top/predictions_{score_kind}.npz')
        scores = data['scores']
        labels = data['labels']
        fpr, tpr, _ = roc_curve(y_true=labels, y_score=-scores)

        ax.plot(tpr, 1. / fpr,
            label=f'Top {roc_auc_score(labels, -scores):.3f}')

    ax.plot(np.linspace(0, 1, 1000), 1. / np.linspace(0, 1, 1000),
        linestyle='--', color='grey')

    ax.grid(which='both')
    ax.legend()
    ax.set_yscale('log')
    ax.set_ylim(0.9, 1e3)
    ax.set_title(f'100 constituents, 30 bins, log probability')
    ax.set_xlabel(r'$\epsilon_S$')
    ax.set_ylabel(r'1 / $\epsilon_B$')
    fig.savefig(f'roc_nC100_nBins30_perp.png')


if __name__ == '__main__':
    # plot_scores(dir=f'N600k_E100_nC100_nBin30_LRcos')
    plot_rocs()
