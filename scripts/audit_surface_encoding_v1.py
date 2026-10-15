"""Audit accepted R4 preprocessing only: no targets read, no model fitted."""
import csv
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import polars as pl
from nfl_edge.backtest.totals_bake_off import build_candidate_model, _pandas_predictors
from nfl_edge.features.totals_v1.feature_table import EXACT_90_COLUMNS

root = Path(__file__).resolve().parents[1]
path = root / 'data/derived/totals_v1_modeling_table_2018_2024.parquet'
# Load predictors alone. Never select target_total_points or any outcome column.
frame = pl.read_parquet(path, columns=list(EXACT_90_COLUMNS))
x = _pandas_predictors(frame, 'ridge')
labels = ['grass', 'a_turf', 'fieldturf', 'matrixturf', 'sportturf', 'astroturf', 'artificial']
probe = x.iloc[[0] * len(labels)].copy()
probe['surface_category'] = labels
with patch('sklearn.linear_model.Ridge.fit', side_effect=AssertionError('model fitting forbidden')) as fit, patch('requests.sessions.Session.request', side_effect=AssertionError('network forbidden')) as network:
    candidate = build_candidate_model('R4')
    features = candidate.named_steps['features']
    features.fit(x)  # label-free vocabulary/scaler construction, not predictive fitting
    encoded = np.asarray(features.transform(probe))
    names = list(features.get_feature_names_out())
    idx = [i for i,n in enumerate(names) if n.startswith('categorical__surface_category_')]
    values = encoded[:,idx]
    distances = {a:{b:float(np.abs(values[i]-values[j]).sum()) for j,b in enumerate(labels)} for i,a in enumerate(labels)}
    result = {'source_modeling_table_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'accepted_candidate':'R4', 'predictor_count':len(EXACT_90_COLUMNS), 'source_predictor_rows':frame.height, 'target_columns_read':[], 'predictive_model_fit_calls':fit.call_count, 'network_requests':network.call_count, 'surface_columns':[names[i] for i in idx], 'encoded_vectors':{a:values[i].tolist() for i,a in enumerate(labels)}, 'pairwise_surface_L1_distance':distances, 'point_prediction_delta_formula':'With all other inputs and fitted state held fixed, y(B)-y(A)=coefficient(B)-coefficient(A). No coefficient or point magnitude measured here.', 'numeric_point_effect_measured':False, 'conclusion':'Separate turf label columns, not a grass/artificial collapse. Distinct columns can affect fitted predictions; this audit does not establish nonzero or practically important coefficient differences.', 'paid_provider_requests':0, 'odds_api_called':False, 'market_data_read':False}
print(json.dumps(result,indent=2))
