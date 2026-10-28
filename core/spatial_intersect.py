import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point


def intersect_two_grids(gdf_a, gdf_b, fid_a, fid_b):
    result = gpd.overlay(gdf_a[[fid_a, 'geometry']],
                         gdf_b[[fid_b, 'geometry']],
                         how='intersection')
    result['area'] = result.geometry.area
    return result


def calc_area_ratio(intersected, group_col, ratio_col='ratio'):
    total_area = intersected.groupby(group_col)['area'].sum().rename('total_area')
    result = intersected.join(total_area, on=group_col)
    result[ratio_col] = result['area'] / result['total_area']
    return result


def allocate_by_area(intersected, source_col, pollutant_cols, fid_source, fid_target='FID_CMAQ'):
    total_area = intersected.groupby(fid_source)['area'].sum().rename('_src_total_area')
    df = intersected.join(total_area, on=fid_source)
    df['_ratio'] = df['area'] / df['_src_total_area']
    for col in pollutant_cols:
        df[f'{col}_alloc'] = df['_ratio'] * df[col]
    result = df.groupby(fid_target)[[f'{c}_alloc' for c in pollutant_cols]].sum()
    result.columns = pollutant_cols
    return result


def allocate_by_length(intersected, source_gdf, pollutant_cols, fid_source, fid_target='FID_CMAQ'):
    intersected['length'] = intersected.geometry.length
    total_len = intersected.groupby(fid_source)['length'].sum().rename('_src_total_len')
    df = intersected.join(total_len, on=fid_source)
    df['_ratio'] = df['length'] / df['_src_total_len']
    for col in pollutant_cols:
        df[f'{col}_alloc'] = df['_ratio'] * df[col]
    result = df.groupby(fid_target)[[f'{c}_alloc' for c in pollutant_cols]].sum()
    result.columns = pollutant_cols
    return result


def allocate_by_points(points_gdf, grid_gdf, fid_target='FID_CMAQ', weight_col=None):
    joined = gpd.sjoin(points_gdf, grid_gdf, how='inner', predicate='within')
    if weight_col and weight_col in joined.columns:
        counts = joined.groupby(fid_target)[weight_col].sum()
    else:
        counts = joined.groupby(fid_target).size()
    return counts
