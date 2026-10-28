import numpy as np
import geopandas as gpd
from shapely.geometry import Polygon
from pyproj import Transformer, CRS


def build_meic_grid(lon_flat, lat_flat, lon_res=0.25, lat_res=0.25, crs="EPSG:4326"):
    half_lon = lon_res / 2
    half_lat = lat_res / 2
    polygons = []
    for lon_c, lat_c in zip(lon_flat, lat_flat):
        corners = [(lon_c - half_lon, lat_c - half_lat), (lon_c + half_lon, lat_c - half_lat),
                   (lon_c + half_lon, lat_c + half_lat), (lon_c - half_lon, lat_c + half_lat)]
        polygons.append(Polygon(corners))
    fid = np.arange(len(polygons))
    return gpd.GeoDataFrame({"FID_MEIC": fid}, geometry=polygons, crs=crs)


def build_cmaq_grid_from_gridcro2d(grid_info):
    nrows = int(grid_info['NROWS'])
    ncols = int(grid_info['NCOLS'])
    xorig = float(grid_info['XORIG'])
    yorig = float(grid_info['YORIG'])
    xcell = float(grid_info['XCELL'])
    ycell = float(grid_info['YCELL'])

    lcc_crs = _build_lcc_crs(grid_info)

    rows = []
    for r in range(nrows):
        for c in range(ncols):
            x_min = xorig + c * xcell
            y_min = yorig + r * ycell
            x_max = x_min + xcell
            y_max = y_min + ycell
            poly = Polygon([
                (x_min, y_min), (x_max, y_min),
                (x_max, y_max), (x_min, y_max)
            ])
            rows.append({
                'FID_CMAQ': r * ncols + c,
                'rownum': r,
                'colnum': c,
                'geometry': poly
            })

    gdf = gpd.GeoDataFrame(rows, crs=lcc_crs)
    gdf = gdf.sort_values('FID_CMAQ').reset_index(drop=True)
    return gdf


def _build_lcc_crs(grid_info):
    p_alp = float(grid_info['P_ALP'])
    p_bet = float(grid_info['P_BET'])
    p_gam = float(grid_info['P_GAM'])
    xcent = float(grid_info['XCENT'])
    ycent = float(grid_info['YCENT'])

    lcc_crs = CRS.from_proj4(
        f"+proj=lcc +lat_1={p_alp} +lat_2={p_bet} "
        f"+lat_0={ycent} +lon_0={p_gam} "
        f"+x_0=0 +y_0=0 +R=6370000 +units=m +no_defs"
    )
    return lcc_crs


def read_cmaq_grid(shp_path, target_crs=None):
    gdf = gpd.read_file(shp_path)
    if target_crs:
        gdf = gdf.to_crs(target_crs)
    if "FID_CMAQ" not in gdf.columns:
        gdf["FID_CMAQ"] = np.arange(len(gdf))
    return gdf


def reproject_gdf(gdf, target_crs):
    return gdf.to_crs(target_crs)


def transform_coords(lon, lat, src_crs="EPSG:4326", dst_crs="EPSG:3857"):
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    x, y = transformer.transform(lon, lat)
    return np.array(x), np.array(y)