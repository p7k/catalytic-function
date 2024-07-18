from src.cross_validation import BatchGridSearch, BatchScriptParams

# Args
dataset_name = 'sprhea'
toc = 'sp_folded_pt' # Name of file with protein id | features/labels | sequence
n_splits = 5
seed = 1234
gs_name = 'simple_rxn_mean_agg_depths_homology_80_0' # Grid search name
allocation = 'b1039'
partition = 'b1039'
mem = '12G' # 12G
time = '18' # Hours 12
fit_script = 'two_channel_fit.py'
neg_multiple = 1
split_strategy = 'homology'
split_sim_threshold = 0.8
batch_script_params = BatchScriptParams(allocation=allocation, partition=partition, mem=mem, time=time, script=fit_script)
embed_type = 'esm'

# Hyperparameters

# RC GNN
hps = {
    'n_epochs':[25], # int
    'pred_head':['dot_sig', 'binary'], # 'binary' | 'dot_sig'
    'message_passing':['bondwise'], # 'bondwise' | 'bondwise_dict' | None
    'agg':['mean'], # 'mean' | 'last' | 'attention' | None
    'd_h_encoder':[20, 50, 300], # int
    'model':['mpnn_dim_red'], # 'mpnn' | 'mpnn_dim_red' | 'ffn' | 'linear'
    'featurizer':['rxn_simple'], # 'rxn_simple' | 'rxn_rc' | 'mfp'
    'encoder_depth':[3, 2, 1], # int | None
    }

gs = BatchGridSearch(
    dataset_name=dataset_name,
    toc=toc,
    neg_multiple=neg_multiple,
    gs_name=gs_name,
    n_splits=n_splits,
    split_strategy=split_strategy,
    embed_type=embed_type,
    seed=seed,
    split_sim_threshold=split_sim_threshold,
    batch_script_params=batch_script_params,
    hps=hps
)

gs.run()

# # Matrix factorization
# hps = {
#     'lr':[5e-3],
#     'max_epochs':[7500],
#     'batch_size':[5],
#     'optimizer__weight_decay':[5e-5],
#     'module__scl_embeds':[True],
#     'neg_multiple': [1],
#     # 'module__n_factors':[20, 50, 100]
#     'user_embeds':["esm_rank_20", "esm_rank_50", "esm_rank_100"]
# }