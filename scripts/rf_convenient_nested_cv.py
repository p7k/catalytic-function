import multiprocessing as mp
from collections import namedtuple
import pickle
import json
import time

ParamSet = namedtuple('ParamSet', 'max_depth, max_samples, max_features, n_estimators')
MetaData = namedtuple('MetaData', 'outer_split, inner_split, hp_idx', defaults=[None for _ in range(3)])

def fit_eval(q_in, q_out, scoring_metrics, lock, do_save=False, train_data_name=None, embed_type=None, timestamp=None):
    while True:
        elt = q_in.get()
        
        if elt is None:
            break
        
        model, X_train, y_train, X_test, y_test, meta_data = elt

        with lock:
            print(f"Fitting: {meta_data}")
        
        fit_tic = time.perf_counter()
        model.fit(X_train, y_train)
        fit_toc = time.perf_counter()

        with lock:
            print(f"Fit {meta_data} in {fit_toc - fit_tic:.2f} seconds")
            print(f"Evaluating: {meta_data}")

        scores = {}
        for name, metric in scoring_metrics.items():
            y_pred = model.predict(X_test)
            scores[name] = metric(y_test, y_pred)
        
        if do_save:
            with lock:
                print(f"Saving: {meta_data}")

            fn = f"{timestamp}_random_forest_train_data_{train_data_name}_{embed_type}_embeddings_model_no_{meta_data.outer_split}"
            
            with open(f"../artifacts/trained_models/{fn}.pkl", 'wb') as f:
                pickle.dump(model, f)

            with open(f"../artifacts/model_evals/{fn}.json", 'w') as f:
                json.dump(scores, f)
        
        q_out.put((scores, meta_data))


if __name__ == '__main__':

    from sklearn.model_selection import KFold
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, roc_auc_score, f1_score, precision_score, recall_score
    from itertools import product
    from src.utils import load_sparse_adj_mat, load_design_matrix
    import numpy as np
    from src.utils import ensure_dirs
    from datetime import datetime
    import scipy as sp

    now = datetime.now()
    timestamp = now.strftime("%y%m%d_%H_%M_%S")

    ensure_dirs("/scratch/spn1560/random_forests")

    # Settings
    train_data_name = 'swissprot'
    embed_type = 'esm'
    outer_kfold = 2
    inner_kfold = 2
    hpo_metric = 'f1_weighted'
    seed = 1234
    do_save = True
    n_cores = 33
    qsize = 1
    inner_eval_name = 'f1_weighted'
    inner_eval_metric = {inner_eval_name : lambda y, y_pred : f1_score(y, y_pred, average='weighted', zero_division=0)}
    rng = np.random.default_rng(seed=seed)

    # Metrics to evaluate generalization error
    gen_metrics = {
        'accuracy': accuracy_score,
        'f1_weighted' : lambda y, y_pred : f1_score(y, y_pred, average='weighted', zero_division=0),
        'recall_weighted' : lambda y, y_pred : recall_score(y, y_pred, average='weighted', zero_division=0),
        'precision_weighted' : lambda y, y_pred : precision_score(y, y_pred, average='weighted', zero_division=0),
        # 'roc_auc_weighted' : lambda y, y_pred : roc_auc_score(y, y_pred, average='weighted'),
        # 'roc_auc_macro' : lambda y, y_pred : roc_auc_score(y, y_pred, average='macro'),
        'f1_samples' : lambda y, y_pred : f1_score(y, y_pred, average='samples', zero_division=0),
        'recall_samples' : lambda y, y_pred : recall_score(y, y_pred, average='samples', zero_division=0),
        'precision_samples' : lambda y, y_pred : precision_score(y, y_pred, average='samples', zero_division=0)
    }

    # Load dataset
    n_classes = 150
    y = sp.sparse.load_npz(f"/scratch/spn1560/swissprot_esm_y_top_{n_classes}_classes.npz")
    y = sp.sparse.csr_matrix(y)
    X = np.load(f"/scratch/spn1560/swissprot_esm_X_top_{n_classes}_classes.npy")
    # y, idx_sample, idx_feature = load_sparse_adj_mat(train_data_name)
    # sample_idx = {v:k for k,v in idx_sample.items()}
    # X = load_design_matrix(train_data_name, embed_type, sample_idx, do_norm=True)


    # Params for grid search
    max_depths = [9] # [3, 5, 7]
    n_estimators = [int(np.sqrt(X.shape[0])), int(np.sqrt(X.shape[0]) * 2)] # [50, 75, 100]
    max_samples = [int(np.sqrt(X.shape[0])), int(np.sqrt(X.shape[0]) * 10)]
    max_features = [int(np.sqrt(X.shape[1])), int(np.sqrt(X.shape[1]) * 10)]
    params = [ParamSet(*elt) for elt in product(max_depths, max_samples, max_features, n_estimators)]
    T = max(n_estimators)

    # Splits for nested cv
    inner_cv = KFold(n_splits=inner_kfold, shuffle=True, random_state=seed)
    outer_cv = KFold(n_splits=outer_kfold, shuffle=True, random_state=seed)

    '''
    Inner CV
    '''
    inner_tic = time.perf_counter()

    # Initialize queues and pool
    to_fit = mp.Queue(maxsize=qsize)
    fitted = mp.Queue()
    the_lock = mp.Lock()
    pool = mp.Pool(n_cores, initializer=fit_eval, initargs=(to_fit, fitted, inner_eval_metric, the_lock))

    # Populate the in queue
    for o, (train_val_idxs, test_idxs) in enumerate(outer_cv.split(X)): # Outer data splits
        for i, (train_idxs, val_idxs) in enumerate(inner_cv.split(X[train_val_idxs])): # Inner data splits
            X_train, y_train = X[train_val_idxs][train_idxs], y[train_val_idxs][train_idxs]
            X_val, y_val = X[train_val_idxs][val_idxs], y[train_val_idxs][val_idxs]
            for h, param in enumerate(params): # Hyperparameter grid search
                model = RandomForestClassifier(n_estimators=param.n_estimators, max_depth=param.max_depth, max_features=param.max_features, random_state=seed)
                meta_data = MetaData(outer_split=o, inner_split=i, hp_idx=h)
                to_fit.put((model, X_train, y_train.toarray(), X_val, y_val.toarray(), meta_data))

                with the_lock:
                    print(f"Queued: {meta_data}")

    # Signal to workers: 'all done'
    for _ in range(n_cores):
        to_fit.put(None)

    pool.close()
    pool.join()

    del X_train, y_train, X_val, y_val

    inner_toc = time.perf_counter()
    print(f"Inner cv took {inner_toc - inner_tic:.2f} seconds")

    '''
    Outer cv
    '''
    outer_tic = time.perf_counter()
    
    # Pull inner cv results out of queue
    inner_res = [np.empty(shape=(len(params), inner_kfold)) for _ in range(outer_kfold)]
    while not fitted.empty():
        scores, meta_data = fitted.get()
        inner_res[meta_data.outer_split][meta_data.hp_idx, meta_data.inner_split] = scores[inner_eval_name]

    # Assemble best inner hps
    best_inner_params = []
    for os in inner_res:
        idx = np.argmax(os.mean(axis=1)) # HPs that gave highest average score
        best_inner_params.append(params[idx])

    # Initialize queues and pool
    to_fit = mp.Queue(maxsize=qsize)
    fitted = mp.Queue()
    the_lock = mp.Lock()
    pool = mp.Pool(n_cores,
                   initializer=fit_eval,
                   initargs=(to_fit, fitted, gen_metrics, the_lock, do_save, train_data_name, embed_type, timestamp) # Gen metrics, save models
                   )

    # Populate the in queue
    for oh, (train_idxs, test_idxs) in enumerate(outer_cv.split(X)): # Outer data splits == Number of inner best hps
        X_train, y_train = X[train_idxs], y[train_idxs]
        X_test, y_test = X[test_idxs], y[test_idxs]
        param = best_inner_params[oh]
        model = RandomForestClassifier(n_estimators=param.n_estimators, max_depth=param.max_depth, max_features=param.max_features, random_state=seed)
        meta_data = MetaData(outer_split=oh)
        to_fit.put((model, X_train, y_train.toarray(), X_test, y_test.toarray(), meta_data))

        with the_lock:
            print(f"Queued: model #{meta_data.outer_split}. Max depth: {param.max_depth}, Max samples: {param.max_samples}, N trees: {param.n_estimators}, Max features: {param.max_features}")

    # Signal to workers: 'all done'
    for _ in range(n_cores):
        to_fit.put(None)

    pool.close()
    pool.join()

    outer_toc = time.perf_counter()
    print(f"Outer cv took {outer_toc - outer_tic:.2f} seconds")

    # Print final results
    while not fitted.empty():
        scores, meta_data = fitted.get()
        print(f"Model #{meta_data.outer_split}: Accuracy = {scores['accuracy']}, F1 = {scores['f1_weighted']}")