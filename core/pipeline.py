import os
import sys
import time
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings as S
from core.meic_reader import MEICReader
from core.grid_builder import build_meic_grid, build_cmaq_grid_from_gridcro2d, reproject_gdf
from core.spatial_intersect import intersect_two_grids, allocate_by_area, allocate_by_length, allocate_by_points
from core.speciate import SpeciationEngine
from core.temporal import TemporalProfile
from core.nc_writer import NCWriter, _compute_grid_info, read_gridcro2d
from core.quality_check import run_quality_check


SOURCE_NAME_MAP = {
    'AG': 'agriculture', 'IN': 'industry', 'PP': 'power',
    'AR': 'residential', 'TR': 'transportation',
}
BASIC_POLLUTANTS = ['SO2', 'NOx', 'CO', 'NH3', 'PM25', 'PM10', 'VOC', 'BC', 'OC']


def find_meic_files(meic_dir, meic_year, month, source_name, pollutants):
    meic_path = Path(meic_dir)
    result = {}
    for p in pollutants:
        fname = f'{meic_year}_{month:02d}_{source_name}_{p}.nc'
        fpath = meic_path / fname
        if fpath.exists():
            result[p] = str(fpath)
    return result


def _resolve_output_dir(output_path):
    p = Path(output_path)
    if p.suffix.lower() == '.nc':
        return str(p.parent) if p.parent != Path('.') else '.'
    return str(p)


def run_pipeline(meic_nc_dir, cmaq_grid_file, landuse_file, pop_file, roads_file,
                template_dir, output_dir=None, start_dt=None, end_dt=None,
                meic_year=None, meic_month=None,
                sources=['AG', 'IN', 'PP', 'AR', 'TR'],
                gridcro2d_file=None, inputtype='month'):
    from datetime import datetime as _dt, timedelta as _td
    if start_dt is None:
        start_dt = _dt(2020, 1, 1, 0)
    if end_dt is None:
        end_dt = _dt(2020, 1, 31, 23)
    if meic_year is None:
        meic_year = start_dt.year
    if meic_month is None:
        meic_month = start_dt.month

    year = start_dt.year
    month = start_dt.month

    if output_dir is None:
        output_dir = r'D:\ai_agent_data'
    output_dir = _resolve_output_dir(output_dir)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print('=' * 60)
    print('  Smart Emission Inventory Pipeline')
    print(f'  Time range: {start_dt.strftime("%Y-%m-%d %H:00")} ~ {end_dt.strftime("%Y-%m-%d %H:00")}')
    print(f'  MEIC data: year={meic_year}, start_month={meic_month}')
    print(f'  Sources: {sources}')
    print(f'  Output dir: {output_dir}')
    print('=' * 60)

    # ===== Stage 1: Grid Setup =====
    print('\n[Stage 1] Grid Setup')

    first_source = SOURCE_NAME_MAP[sources[0]]
    first_files = find_meic_files(meic_nc_dir, meic_year, month, first_source, ['SO2'])
    if not first_files:
        print(f'ERROR: No MEIC files found in {meic_nc_dir}')
        return None

    first_nc = list(first_files.values())[0]
    print(f'  MEIC from: {os.path.basename(first_nc)}')
    with MEICReader(first_nc) as mr:
        lon_flat, lat_flat = mr.get_coords_flat()
        meic_grid_wgs84 = build_meic_grid(lon_flat, lat_flat, mr.lon_res, mr.lat_res)
    print(f'  MEIC cells: {len(meic_grid_wgs84)}')

    cmaq_grid = gpd.read_file(cmaq_grid_file)
    if 'FID_CMAQ' not in cmaq_grid.columns:
        cmaq_grid['FID_CMAQ'] = np.arange(len(cmaq_grid))
    print(f'  CMAQ cells: {len(cmaq_grid)}')

    # ===== Stage 2: Intersect =====
    print('\n[Stage 2] Grid Intersection')

    if gridcro2d_file and os.path.exists(gridcro2d_file):
        grid_info = read_gridcro2d(gridcro2d_file)
        cmaq_grid_from_gc2d = build_cmaq_grid_from_gridcro2d(grid_info)
        cmaq_lcc = cmaq_grid_from_gc2d
        print(f'  CMAQ grid built from GRIDCRO2D: {len(cmaq_lcc)} cells')
        print(f'  CRS: {cmaq_lcc.crs}')

        if len(cmaq_grid) != len(cmaq_lcc):
            print(f'  WARNING: Shapefile has {len(cmaq_grid)} cells, GRIDCRO2D has {len(cmaq_lcc)} cells')
            print(f'  Using GRIDCRO2D grid for intersection')
    else:
        cmaq_lcc = cmaq_grid.copy()
        cmaq_lcc.crs = S.LCC_CMAQ

    meic_lcc = reproject_gdf(meic_grid_wgs84, cmaq_lcc.crs)

    t0_sub = time.time()
    xiangj = intersect_two_grids(meic_lcc, cmaq_lcc, 'FID_MEIC', 'FID_CMAQ')
    print(f'  {len(xiangj)} fragments in {time.time()-t0_sub:.1f}s')

    # ===== Stage 3-6: Per-month MEIC → Spatial → Speciation =====
    from datetime import datetime as _dt2, timedelta as _td2

    sim_months = []
    cur = start_dt
    while cur <= end_dt:
        key = (cur.year, cur.month)
        if key not in sim_months:
            sim_months.append(key)
        cur += _td2(days=32)
        cur = cur.replace(day=1)

    meic_month_offset = meic_month - start_dt.month
    meic_months_for_sim = []
    for sy, sm in sim_months:
        mm = sm + meic_month_offset
        my = meic_year
        while mm > 12:
            mm -= 12
            my += 1
        while mm < 1:
            mm += 12
            my -= 1
        meic_months_for_sim.append((my, mm))

    print(f'  Simulation months: {["{:04d}-{:02d}".format(y,m) for y,m in sim_months]}')
    print(f'  MEIC data months:  {["{:04d}-{:02d}".format(y,m) for y,m in meic_months_for_sim]}')

    # ===== Stage 3.5: MEIC Area Ratio (step3_ratio) =====
    print('\n  Computing MEIC area ratio (boundary correction)...')
    meic_area_in_cmaq = xiangj.groupby('FID_MEIC')['area'].sum()
    meic_full_area = meic_lcc.geometry.area
    meic_full_area.index = meic_lcc['FID_MEIC'].values
    step3_ratio = (meic_area_in_cmaq / meic_full_area).rename('step3_ratio')
    step3_ratio = step3_ratio.clip(upper=1.0)
    n_truncated = int((step3_ratio < 0.999).sum())
    n_total = len(step3_ratio)
    print(f'  MEIC grids in CMAQ domain: {n_total}')
    print(f'  Truncated (ratio < 1.0): {n_truncated}')
    if n_truncated > 0:
        print(f'  Min ratio: {step3_ratio.min():.4f}, '
              f'Mean ratio of truncated: {step3_ratio[step3_ratio < 0.999].mean():.4f}')
    else:
        print(f'  All MEIC grids fully inside CMAQ domain')

    target_crs = cmaq_lcc.crs

    landuse = gpd.read_file(landuse_file)
    landuse_lcc = landuse.to_crs(target_crs)

    landuse_lcc['_FID_LU'] = np.arange(len(landuse_lcc))
    print('\n  Pre-intersect: Landuse x CMAQ-MEIC fragments...')
    lu_x_frag = gpd.overlay(
        landuse_lcc[['_FID_LU', 'gridcode', 'geometry']],
        xiangj[['FID_MEIC', 'FID_CMAQ', 'geometry']],
        how='intersection',
        keep_geom_type=False
    )
    lu_x_frag['area'] = lu_x_frag.geometry.area
    lu_x_frag = lu_x_frag[lu_x_frag['FID_CMAQ'].notna() & lu_x_frag['FID_MEIC'].notna()]
    print(f'    Got {len(lu_x_frag)} triple-fragments')

    pop_lcc = None
    if 'AR' in sources:
        print('  Loading population data...')
        pop = gpd.read_file(pop_file)
        pop_lcc = pop.to_crs(target_crs)

    roads_prepared = None
    if 'TR' in sources:
        print('  Loading & preparing road network...')
        roads = gpd.read_file(roads_file)
        if 'fclass' in roads.columns:
            motor_classes = [
                'motorway', 'trunk', 'primary', 'secondary', 'tertiary',
                'unclassified', 'residential', 'service',
                'motorway_link', 'trunk_link', 'primary_link', 'secondary_link',
            ]
            roads = roads[roads['fclass'].isin(motor_classes)].copy()
        roads_lcc = roads.to_crs(target_crs)
        roads_lcc = roads_lcc[['geometry']].copy()
        cmaq_union = cmaq_lcc.unary_union
        roads_lcc = roads_lcc[roads_lcc.intersects(cmaq_union)].copy()
        if len(roads_lcc) > 0:
            roads_lcc['_FID_ROAD'] = np.arange(len(roads_lcc))
            print(f'    Roads after filter: {len(roads_lcc):,}')
            print('    Overlaying roads x CMAQ-MEIC fragments...')
            t_road = time.time()
            road_x_frag = gpd.overlay(
                roads_lcc[['_FID_ROAD', 'geometry']],
                xiangj[['FID_MEIC', 'FID_CMAQ', 'geometry']],
                how='intersection',
                keep_geom_type=False
            )
            road_x_frag['_seg_len'] = road_x_frag.geometry.length
            road_x_frag = road_x_frag[
                road_x_frag['FID_MEIC'].notna() & road_x_frag['FID_CMAQ'].notna()
            ]
            road_len_per_meic = road_x_frag.groupby('FID_MEIC')['_seg_len'].sum().rename('_road_total')
            road_x_frag = road_x_frag.join(road_len_per_meic, on='FID_MEIC')
            road_x_frag = road_x_frag.join(step3_ratio, on='FID_MEIC')
            print(f'    Overlay done in {time.time()-t_road:.1f}s, {len(road_x_frag):,} fragments')
            roads_prepared = road_x_frag
        else:
            print('    No roads in CMAQ domain')

    if 'AR' in sources and pop_lcc is not None:
        print('  Pre-joining population x CMAQ-MEIC fragments...')
        joined_pop = gpd.sjoin(pop_lcc, xiangj[['FID_MEIC', 'FID_CMAQ', 'geometry']],
                               how='inner', predicate='within')
        counts_base = joined_pop.groupby(['FID_MEIC', 'FID_CMAQ']).size().reset_index(name='_n')
        total_by_meic = counts_base.groupby('FID_MEIC')['_n'].sum().rename('_total')
    else:
        counts_base = None
        total_by_meic = None

    cmaq_fids = cmaq_lcc['FID_CMAQ'].values

    speciator = SpeciationEngine(template_dir)
    speciator.load_all(sources)

    speciated_by_month = {}
    meic_totals_original = {}

    for mi, ((sim_y, sim_m), (my, mm)) in enumerate(zip(sim_months, meic_months_for_sim)):
        print(f'\n[Stage 3-6] Month {sim_y}-{sim_m:02d} (MEIC data: {my}-{mm:02d})')

        meic_data_by_source = {}
        for src in sources:
            src_name = SOURCE_NAME_MAP[src]
            files = find_meic_files(meic_nc_dir, my, mm, src_name, BASIC_POLLUTANTS)
            if not files:
                print(f'  [{src}] No files found for {my}_{mm:02d}')
                continue

            print(f'  [{src}] {len(files)} pollutants from {my}_{mm:02d}...')
            data_dict = {}
            for pollutant, nc_path in files.items():
                with MEICReader(nc_path) as mr:
                    z = mr.get_data()
                data_dict[pollutant] = z
                meic_totals_original.setdefault(pollutant, 0.0)
                meic_totals_original[pollutant] += float(z.sum())

            df = pd.DataFrame(data_dict)
            df['FID_MEIC'] = np.arange(len(df))
            meic_data_by_source[src] = df

        pollutants_found = sorted(set(
            col for df in meic_data_by_source.values() for col in df.columns if col != 'FID_MEIC'
        ))
        if not pollutants_found:
            print(f'  No pollutants found, skipping month')
            continue

        print(f'  Pollutants: {pollutants_found}')

        emissions_by_source = {}

        for src, (codes, label) in [('AG', (S.LANDUSE_FARM, 'Farmland')),
                                    ('IN', (S.LANDUSE_INDUSTRY, 'Industrial')),
                                    ('PP', (S.LANDUSE_URBAN, 'Urban'))]:
            if src not in sources or src not in meic_data_by_source:
                continue

            lu_sel = lu_x_frag[lu_x_frag['gridcode'].isin(codes)].copy()
            if len(lu_sel) == 0:
                continue

            meic_src = meic_data_by_source[src][['FID_MEIC'] + pollutants_found]
            lu_sel = lu_sel.join(meic_src.set_index('FID_MEIC'), on='FID_MEIC')
            lu_sel = lu_sel.dropna(subset=pollutants_found, how='all')
            lu_sel = lu_sel.join(step3_ratio, on='FID_MEIC')

            total_area_per_meic = lu_sel.groupby('FID_MEIC')['area'].sum().rename('_total_area')
            lu_sel = lu_sel.join(total_area_per_meic, on='FID_MEIC')

            result = pd.DataFrame(index=cmaq_fids)
            for p in pollutants_found:
                lu_sel[f'_alloc_{p}'] = lu_sel[p] * lu_sel['area'] / lu_sel['_total_area'] * lu_sel['step3_ratio']
                col = lu_sel.groupby('FID_CMAQ')[f'_alloc_{p}'].sum()
                result = result.join(col.rename(p), how='left')
            result = result.fillna(0)
            emissions_by_source[src] = result[pollutants_found]

        if 'AR' in sources and 'AR' in meic_data_by_source and counts_base is not None:
            meic_ar = meic_data_by_source['AR'].set_index('FID_MEIC')
            result_ar = pd.DataFrame(index=cmaq_fids)
            for p in pollutants_found:
                counts = counts_base.copy()
                counts = counts.join(total_by_meic, on='FID_MEIC')
                counts['_ratio'] = counts['_n'] / counts['_total']
                counts = counts.join(meic_ar[p].rename('_src_val'), on='FID_MEIC')
                counts = counts.join(step3_ratio, on='FID_MEIC')
                counts[p] = counts['_ratio'] * counts['_src_val'] * counts['step3_ratio']
                col = counts.groupby('FID_CMAQ')[p].sum()
                result_ar = result_ar.join(col, how='left')
            result_ar = result_ar.fillna(0)
            emissions_by_source['AR'] = result_ar[pollutants_found]

        if 'TR' in sources and 'TR' in meic_data_by_source and roads_prepared is not None:
            meic_tr = meic_data_by_source['TR'][['FID_MEIC'] + pollutants_found]
            rxf = roads_prepared.join(meic_tr.set_index('FID_MEIC'), on='FID_MEIC')
            rxf = rxf.dropna(subset=pollutants_found, how='all')
            if len(rxf) > 0:
                result_tr = pd.DataFrame(index=cmaq_fids)
                for p in pollutants_found:
                    rxf[f'_alloc_{p}'] = rxf[p] * rxf['_seg_len'] / rxf['_road_total'] * rxf['step3_ratio']
                    col = rxf.groupby('FID_CMAQ')[f'_alloc_{p}'].sum()
                    result_tr = result_tr.join(col.rename(p), how='left')
                result_tr = result_tr.fillna(0)
                emissions_by_source['TR'] = result_tr[pollutants_found]

        for src in emissions_by_source:
            t = emissions_by_source[src].sum()
            print(f'  [{src}] SO2={t.get("SO2",0):.3e}, NOx={t.get("NOx",0):.3e}')

        speciated_month = {}
        for src in sources:
            if src in emissions_by_source:
                df = emissions_by_source[src]
                spec_df = speciator.speciate(df, src)
                speciated_month[src] = spec_df

        speciated_by_month[(sim_y, sim_m)] = speciated_month

    all_species = sorted(set(
        col for month_dict in speciated_by_month.values()
        for src_df in month_dict.values()
        for col in src_df.columns
    ))
    print(f'\n  Total unique species across all months: {len(all_species)}')

    # ===== Stage 7: Quality Check =====
    print('\n[Stage 7] Quality Check')
    if emissions_by_source:
        run_quality_check(emissions_by_source, meic_totals_original)

    # ===== Stage 8: Write NC per source =====
    print('\n[Stage 8] Writing IOAPI NC (per source)')

    if gridcro2d_file and os.path.exists(gridcro2d_file):
        print(f'  Reading grid params from GRIDCRO2D: {gridcro2d_file}')
        grid_info = read_gridcro2d(gridcro2d_file)
        ROW = grid_info['NROWS']
        COL = grid_info['NCOLS']
        print(f'  GRIDCRO2D: ROW={ROW}, COL={COL}')
        print(f'  GDTYP={grid_info["GDTYP"]}, P_ALP={grid_info["P_ALP"]}, '
              f'P_BET={grid_info["P_BET"]}, P_GAM={grid_info["P_GAM"]:.4f}')
        print(f'  XORIG={grid_info["XORIG"]:.1f}, YORIG={grid_info["YORIG"]:.1f}')
        print(f'  XCELL={grid_info["XCELL"]:.1f}, YCELL={grid_info["YCELL"]:.1f}')
        print(f'  VGTYP={grid_info["VGTYP"]}, VGTOP={grid_info["VGTOP"]:.1f}, '
              f'VGLVLS={grid_info["VGLVLS"]}')
        if 'GDNAM' in grid_info:
            print(f'  GDNAM={grid_info["GDNAM"]}')
    else:
        if gridcro2d_file:
            print(f'  WARNING: GRIDCRO2D not found: {gridcro2d_file}, falling back to shapefile')
        else:
            print(f'  WARNING: No GRIDCRO2D specified, falling back to shapefile')
        from core.nc_writer import _compute_grid_info
        grid_info = _compute_grid_info(cmaq_lcc, S.LCC_CMAQ)
        print(f'  Grid params from shapefile: XORIG={grid_info["XORIG"]:.1f}, '
              f'YORIG={grid_info["YORIG"]:.1f}')
        print(f'  XCELL={grid_info["XCELL"]:.1f}, YCELL={grid_info["YCELL"]:.1f}')

    if gridcro2d_file and os.path.exists(gridcro2d_file) and 'rownum' in cmaq_lcc.columns:
        sf_ROW = int(cmaq_lcc['rownum'].max()) + 1
        sf_COL = int(cmaq_lcc['colnum'].max()) + 1
        _rn = cmaq_lcc['rownum'].astype(int).values
        _cn = cmaq_lcc['colnum'].astype(int).values
        rowmajor_index = np.argsort(_rn * sf_COL + _cn)
    elif 'rownum' in cmaq_grid.columns and 'colnum' in cmaq_grid.columns:
        sf_ROW = int(cmaq_grid['rownum'].max()) + 1
        sf_COL = int(cmaq_grid['colnum'].max()) + 1
        _rn = cmaq_grid['rownum'].astype(int).values
        _cn = cmaq_grid['colnum'].astype(int).values
        rowmajor_index = np.argsort(_rn * sf_COL + _cn)
    else:
        n = len(cmaq_grid)
        best = None
        for r in range(1, int(np.sqrt(n)) + 2):
            if n % r == 0:
                c = n // r
                if best is None or abs(r - c) < abs(best[0] - best[1]):
                    best = (r, c)
        sf_ROW, sf_COL = best[1], best[0]
        rowmajor_index = np.arange(len(cmaq_fids))

    if gridcro2d_file and os.path.exists(gridcro2d_file):
        if sf_ROW != ROW or sf_COL != COL:
            print(f'  WARNING: shapefile ROW={sf_ROW},COL={sf_COL} != '
                  f'GRIDCRO2D ROW={ROW},COL={COL}')
            print(f'  Using GRIDCRO2D dimensions (ROW={ROW}, COL={COL})')
        else:
            print(f'  [OK] shapefile dimensions match GRIDCRO2D: ROW={ROW}, COL={COL}')
    else:
        ROW = sf_ROW
        COL = sf_COL

    assert ROW * COL == len(cmaq_fids), f'ROW*COL={ROW*COL} != Ncells={len(cmaq_fids)}'
    print(f'  Final grid: ROW={ROW}, COL={COL}')

    order_match = np.array_equal(rowmajor_index, np.arange(len(cmaq_fids)))
    if not order_match:
        print(f'  [!] shapefile 行顺序 != row-major, 强制重排 ({len(rowmajor_index)} cells)')
    else:
        print(f'  [OK] shapefile 已是 row-major 顺序')

    ordered_fids = cmaq_fids[rowmajor_index]

    from datetime import datetime as _dt, timedelta as _td
    n_hours = int((end_dt - start_dt).total_seconds() / 3600) + 1

    jday = int(start_dt.strftime('%j'))
    sdate = start_dt.year * 1000 + jday
    stime = start_dt.hour * 10000

    print(f'  Time: {start_dt.strftime("%Y-%m-%d %H:00")} ~ {end_dt.strftime("%Y-%m-%d %H:00")} ({n_hours} hours)')
    print(f'  SDATE={sdate}, STIME={stime}')

    writer = NCWriter()
    temporal = TemporalProfile(template_dir)

    written_files = []
    for src in sources:
        src_has_data = any(
            src in speciated_by_month[mk] for mk in speciated_by_month
        )
        if not src_has_data:
            print(f'  [{src}] SKIP (no data)')
            continue

        species_for_nc = speciator.species_order(src)
        if not species_for_nc:
            species_for_nc = sorted(set(
                col for mk in speciated_by_month
                if src in speciated_by_month[mk]
                for col in speciated_by_month[mk][src].columns
            ))

        emissions_3d = np.zeros((n_hours, len(cmaq_fids), len(species_for_nc)), dtype=np.float32)

        for (sim_y, sim_m), speciated_month in speciated_by_month.items():
            if src not in speciated_month:
                continue

            spec_df = speciated_month[src].reindex(ordered_fids).fillna(0)

            month_start = max(start_dt, _dt(sim_y, sim_m, 1, 0))
            if sim_m == 12:
                month_end_dt = _dt(sim_y + 1, 1, 1, 0) - _td(hours=1)
            else:
                month_end_dt = _dt(sim_y, sim_m + 1, 1, 0) - _td(hours=1)
            month_end = min(end_dt, month_end_dt)

            if month_start > month_end:
                continue

            profile_key = S.SOURCE_PROFILE_KEY.get(src, src)
            temp_factors = temporal.build_temporal_matrix_range(
                month_start, month_end, profile_key, inputtype=inputtype
            )

            h_start = int((month_start - start_dt).total_seconds() / 3600)
            n_h = len(temp_factors)

            for sp_idx, sp_name in enumerate(species_for_nc):
                if sp_name in spec_df.columns:
                    hourly_vals = spec_df[sp_name].fillna(0).values.astype(np.float32)
                else:
                    hourly_vals = np.zeros(len(cmaq_fids), dtype=np.float32)
                emissions_3d[h_start:h_start + n_h, :, sp_idx] += (
                    hourly_vals[np.newaxis, :] * temp_factors[:, np.newaxis] / 3600.0
                )

        out_name = f'{src}area.nc'
        out_path = str(Path(output_dir) / out_name)
        writer.create_ioapi_emission(
            output_path=out_path,
            row_col=(ROW, COL),
            species_names=species_for_nc,
            emissions_tstep_sp=emissions_3d,
            sdate=sdate,
            stime=stime,
            lay=1,
            tstep_val=10000,
            grid_info=grid_info,
            species_units=speciator.species_units(src),
        )
        written_files.append(out_path)
        size_mb = os.path.getsize(out_path) / 1024 / 1024
        print(f'  [{src}] {out_name} ({size_mb:.1f} MB, {len(species_for_nc)} species)')

    elapsed = time.time() - t0
    print(f'\n=== DONE! ({elapsed:.1f}s) ===')
    print(f'Output files ({len(written_files)}):')
    for f in written_files:
        print(f'  {f}')
    return written_files