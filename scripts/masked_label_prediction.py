import pandas as pd
from collections import defaultdict
import os
from src.utils import load_embed, save_json
import numpy as np


'''
Set these
'''
db = 'price'
embed_type = 'clean'

save_acc = f"../artifacts/embed_analysis/masked_label_prediction_acc_{db}_{embed_type}.txt"
db_dir = f"../data/{db}/"
embed_dir = f"{db_dir}{embed_type}/"
embed_csv = f"{db_dir}{db}.csv"
swissprot_clean_dir = '../data/swissprot/clean/'
swissprot_csv = '../data/swissprot/swissprot.csv'
n_levels = 4 # Levels of hierarchy in EC
batch_size = 10 # For getting predicted ec labels

# Load swissprot id -> ec look-up table
swiss_id2ec = pd.read_csv(swissprot_csv, delimiter='\t')
swiss_id2ec.set_index('Entry', inplace=True)

# Load swissprot embeddings
print("Loading swissprot")
swissprot_embeds = []
embed_idxs = defaultdict(lambda : defaultdict(list)) # {ec level: {ec number up to level:[idx1, ...]}} (idxs in embed_arr)
for i, elt in enumerate(os.listdir(swissprot_clean_dir)):
    id, this_embed = load_embed(swissprot_clean_dir + elt)
    this_ec = swiss_id2ec.loc[id, 'EC number']
    
    if ';' in this_ec: # Multiple ecs, take first
        this_ec = this_ec.split(';')[0]

    swissprot_embeds.append(this_embed)

    # Append idxs for all sub-ecs of this embed
    for j in range(n_levels):
        sub_key = '.'.join(this_ec.split('.')[:j+1])
        embed_idxs[j][sub_key].append(i)

swissprot_embeds = np.vstack(swissprot_embeds)

# Load test dataset id -> ec look-up table
id2ec = pd.read_csv(embed_csv, delimiter='\t')
id2ec.set_index('Entry', inplace=True)

# Load test dataset embeddings
ecs = []
embeds = []
for i, elt in enumerate(os.listdir(embed_dir)):
    id, this_embed = load_embed(embed_dir + elt)
    this_ec = id2ec.loc[id, 'EC number']
    
    if ';' in this_ec: # Multiple ecs, take first
        this_ec = this_ec.split(';')[0]

    ecs.append(np.array(this_ec.split('.')).astype('<U1')) # EC str -> arr
    embeds.append(this_embed)

embeds = np.vstack(embeds)
ecs = np.vstack(ecs)

mask_accuracy = [] # Store accuracy masking at all 4 levels
n_samples = embeds.shape[0]
for l in range(n_levels):
    # Get lth-level centroids
    l_ecs = [] 
    l_centroids = []
    for this_l_ec in embed_idxs[l]:
        this_embeds = swissprot_embeds[embed_idxs[l][this_l_ec]]
        ec_arr = np.array(this_l_ec.split('.')).astype('<U1') 
        l_ecs.append(ec_arr)
        l_centroids.append(this_embeds.mean(axis=0))

    l_centroids = np.vstack(l_centroids)
    l_ecs = np.array(l_ecs)

    # Get predicted ec label
    # Batch process samples to save memory
    pred_ecs = []
    n_batches = embeds.shape[0] // batch_size
    l_centroids_expand = np.transpose(l_centroids[np.newaxis, :, :], axes=(0,2,1)) # Transpose to (1, # features, # centroids)
    for i in range(n_batches):
        if i == n_batches - 1:
            dist_to_centroids = np.sqrt(np.square(embeds[i * batch_size:, :, np.newaxis] - l_centroids_expand).sum(axis=1))
        else:
            dist_to_centroids = np.sqrt(np.square(embeds[i * batch_size:(i + 1) * batch_size, :, np.newaxis] - l_centroids_expand).sum(axis=1))
        
        this_pred_ecs = l_ecs[np.argmin(dist_to_centroids, axis=1)]
        pred_ecs.append(this_pred_ecs)

    # Compare predicted to actual
    pred_ecs = np.vstack(pred_ecs)
    this_acc = (np.all(pred_ecs == ecs[:,:l+1], axis=1)).astype(int).sum(axis=0) / n_samples
    mask_accuracy.append(this_acc)
    print("Done w/ level: ", l+1)

# Save
print("Saving")
with open(save_acc, 'w') as f:
    for elt in mask_accuracy:
        f.write(str(elt) + '\n')

print("Done")