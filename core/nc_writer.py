import os
import shutil
import time
import tempfile
import numpy as np
import netCDF4 as nc
from datetime import datetime, timedelta
import pyproj


_CLASSIC_MAX_BYTES = 2147483647

_AEROSOL_SPECIES = {
    'PAL', 'PCA', 'PCL', 'PEC', 'PFE', 'PH2O', 'PK', 'PMC', 'PMFINE',
    'PMG', 'PMN', 'PMOTHR', 'PNA', 'PNCOM', 'PNH4', 'PNO3', 'POC',
    'PSI', 'PSO4', 'PTI', 'PM10', 'PM25', 'UMC', 'EC', 'OC', 'DUST',
    'SEASALT', 'ASO4', 'ANO3', 'ANH4', 'AEC', 'AOC', 'A25', 'A10',
}

_IOAPI_ATTR_ORDER = [
    'IOAPI_VERSION', 'EXEC_ID', 'FTYPE', 'CDATE', 'CTIME', 'WDATE', 'WTIME',
    'SDATE', 'STIME', 'TSTEP', 'NTHIK', 'NCOLS', 'NROWS', 'NLAYS', 'NVARS',
    'GDTYP', 'P_ALP', 'P_BET', 'P_GAM', 'XCENT', 'YCENT', 'XORIG', 'YORIG',
    'XCELL', 'YCELL', 'VGTYP', 'VGTOP', 'VGLVLS', 'GDNAM', 'UPNAM',
    'FILEDESC', 'HISTORY', 'VAR-LIST',
]


def _is_ascii_path(path):
    try:
        str(path).encode('ascii')
        return True
    except (UnicodeEncodeError, AttributeError):
        return False


def _ascii_scratch_dir():
    candidates = []
    sysroot = os.environ.get('SystemRoot')
    if sysroot:
        candidates.append(os.path.join(sysroot, '_sei_nc4_tmp'))
    candidates.append(r'C:\Windows\_sei_nc4_tmp')
    candidates.append(r'C:\_sei_nc4_tmp')
    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, '.probe')
            with open(probe, 'w') as fh:
                fh.write('ok')
            os.remove(probe)
            return d
        except Exception:
            continue
    return tempfile.mkdtemp(prefix='sei_nc_')


def _open_nc4_safe(filepath):
    abs_path = os.path.abspath(filepath)
    if _is_ascii_path(abs_path):
        return nc.Dataset(abs_path, 'r')
    scratch = _ascii_scratch_dir()
    tmp_path = os.path.join(scratch, 'src_%d_%d.nc' % (os.getpid(), int(time.time() * 1000)))
    shutil.copy2(abs_path, tmp_path)
    return nc.Dataset(tmp_path, 'r'), tmp_path


def _close_nc4_safe(ds, tmp_path=None):
    ds.close()
    if tmp_path is not None and os.path.exists(tmp_path):
        os.remove(tmp_path)


def read_gridcro2d(gridcro2d_path):
    result = _open_nc4_safe(gridcro2d_path)
    if isinstance(result, tuple):
        ds, tmp_path = result
    else:
        ds = result
        tmp_path = None

    try:
        grid_info = {
            'NROWS': int(ds.NROWS),
            'NCOLS': int(ds.NCOLS),
            'NLAYS': int(getattr(ds, 'NLAYS', 1)),
            'NTHIK': int(getattr(ds, 'NTHIK', 1)),
            'GDTYP': int(ds.GDTYP),
            'P_ALP': float(ds.P_ALP),
            'P_BET': float(ds.P_BET),
            'P_GAM': float(ds.P_GAM),
            'XCENT': float(ds.XCENT),
            'YCENT': float(ds.YCENT),
            'XORIG': float(ds.XORIG),
            'YORIG': float(ds.YORIG),
            'XCELL': float(ds.XCELL),
            'YCELL': float(ds.YCELL),
            'VGTYP': int(ds.VGTYP),
            'VGTOP': float(ds.VGTOP),
            'VGLVLS': np.array(ds.VGLVLS, dtype=np.float32),
            'global_attrs': [(a, getattr(ds, a)) for a in ds.ncattrs()],
        }
        if hasattr(ds, 'GDNAM'):
            gdn = ds.GDNAM
            if isinstance(gdn, bytes):
                gdn = gdn.decode('utf-8', errors='replace')
            grid_info['GDNAM'] = str(gdn).strip()
    finally:
        _close_nc4_safe(ds, tmp_path)

    return grid_info


def _compute_grid_info(cmaq_gdf, proj_crs):
    xs = cmaq_gdf.geometry.apply(lambda g: g.bounds[0])
    xe = cmaq_gdf.geometry.apply(lambda g: g.bounds[2])
    ys = cmaq_gdf.geometry.apply(lambda g: g.bounds[1])
    ye = cmaq_gdf.geometry.apply(lambda g: g.bounds[3])

    xcell = float(np.median(xe - xs))
    ycell = float(np.median(ye - ys))
    xorig = float(xs.min())
    yorig = float(ys.min())

    p = pyproj.Proj(proj_crs)
    pdict = p.crs.to_dict()
    p_alp = float(pdict.get('lat_1', 25.0))
    p_bet = float(pdict.get('lat_2', 47.0))
    p_gam = float(pdict.get('lon_0', 105.0))
    lat_0 = float(pdict.get('lat_0', 40.0))

    return {
        'XORIG': xorig, 'YORIG': yorig,
        'XCELL': xcell, 'YCELL': ycell,
        'XCENT': p_gam, 'YCENT': lat_0,
        'P_ALP': p_alp, 'P_BET': p_bet, 'P_GAM': p_gam,
    }


class NCWriter:
    def __init__(self):
        pass

    @staticmethod
    def _species_unit(name):
        if name in _AEROSOL_SPECIES:
            return 'g/s'
        return 'moles/s'

    def create_ioapi_emission(self, output_path, row_col, species_names,
                              emissions_tstep_sp, sdate, stime=0,
                              lay=1, tstep_val=10000,
                              grid_info=None, species_units=None):
        output_path = os.path.abspath(str(output_path))
        ROW, COL = int(row_col[0]), int(row_col[1])
        n_species = len(species_names)
        n_steps = int(emissions_tstep_sp.shape[0])

        year = sdate // 1000
        jday = sdate % 1000
        base_date = datetime(year, 1, 1) + timedelta(days=jday - 1)
        start_dt = base_date + timedelta(hours=int(stime) // 10000)

        est_bytes = n_steps * n_species * ROW * COL * 4
        header_margin = 2 * 1024 * 1024
        if est_bytes + header_margin <= _CLASSIC_MAX_BYTES:
            fmt = 'NETCDF3_CLASSIC'
        else:
            fmt = 'NETCDF3_64BIT_OFFSET'
            print(
                f'  WARNING: estimated size {est_bytes / 1024 / 1024:.1f} MB '
                f'exceeds classic limit {_CLASSIC_MAX_BYTES / 1024 / 1024:.1f} MB, '
                f'using NETCDF3_64BIT_OFFSET'
            )
        print(f'  NC format: {fmt} (estimated {est_bytes / 1024 / 1024:.1f} MB)')

        direct = _is_ascii_path(output_path)
        if direct:
            write_path = output_path
            tmp_path = None
        else:
            scratch = _ascii_scratch_dir()
            tmp_path = os.path.join(
                scratch, 'out_%d_%d.nc' % (os.getpid(), int(time.time() * 1000))
            )
            write_path = tmp_path

        try:
            self._write_file(
                write_path, fmt, ROW, COL, species_names, emissions_tstep_sp,
                n_steps, lay, n_species, sdate, stime, tstep_val, start_dt,
                grid_info, species_units,
            )
        except RuntimeError as exc:
            if fmt != 'NETCDF3_CLASSIC':
                raise
            print(f'  WARNING: classic write failed ({exc}), retrying with NETCDF3_64BIT_OFFSET')
            fmt = 'NETCDF3_64BIT_OFFSET'
            if os.path.exists(write_path):
                os.remove(write_path)
            self._write_file(
                write_path, fmt, ROW, COL, species_names, emissions_tstep_sp,
                n_steps, lay, n_species, sdate, stime, tstep_val, start_dt,
                grid_info, species_units,
            )

        if not direct:
            out_dir = os.path.dirname(output_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            if os.path.exists(output_path):
                os.remove(output_path)
            shutil.move(tmp_path, output_path)

        print(f'NC file written: {output_path}')
        return output_path

    def _write_file(self, outfile, fmt, ROW, COL, species_names,
                    emissions_tstep_sp, n_steps, lay, n_species, sdate, stime,
                    tstep_val, start_dt, grid_info, species_units):
        root = nc.Dataset(outfile, 'w', format=fmt)

        root.createDimension('TSTEP', None)
        root.createDimension('DATE-TIME', 2)
        root.createDimension('LAY', int(lay))
        root.createDimension('VAR', n_species)
        root.createDimension('ROW', ROW)
        root.createDimension('COL', COL)

        tflag_var = root.createVariable('TFLAG', 'i4', ('TSTEP', 'VAR', 'DATE-TIME'))
        tflag_var.units = '<YYYYDDD,HHMMSS>'
        tflag_var.long_name = 'TFLAG'
        tflag_var.var_desc = 'Timestep-valid flags:  (1) YYYYDDD or (2) HHMMSS'

        varl = ''
        for sp in species_names:
            var = root.createVariable(sp, 'f4', ('TSTEP', 'LAY', 'ROW', 'COL'))
            var.long_name = '%-16s' % sp
            if species_units and sp in species_units:
                unit = str(species_units[sp])
            else:
                unit = self._species_unit(sp)
            var.units = '%-16s' % unit
            var.var_desc = '%-14s' % ('Model species ' + '%-66s' % sp)
            varl += sp.ljust(16)

        self._set_global_attrs(root, grid_info, ROW, COL, lay, n_species,
                               sdate, stime, tstep_val, varl)

        tflag = np.ones((n_steps, n_species, 2), dtype=np.int32)
        for t in range(n_steps):
            cur = start_dt + timedelta(hours=t)
            date_val = cur.year * 1000 + int(cur.strftime('%j'))
            time_val = cur.hour * 10000 + cur.minute * 100 + cur.second
            tflag[t, :, 0] = date_val
            tflag[t, :, 1] = time_val
        tflag_var[:] = tflag

        for idx, sp in enumerate(species_names):
            species_slice = emissions_tstep_sp[:, :, idx]
            data = species_slice.reshape(n_steps, lay, ROW, COL).astype(np.float32)
            root.variables[sp][:] = data

        root.close()

    def _set_global_attrs(self, root, grid_info, ROW, COL, lay, n_species,
                          sdate, stime, tstep_val, varl):
        gi = grid_info or {}

        src = {}
        for name, value in gi.get('global_attrs', []):
            src[name] = value

        vgtyp = int(gi.get('VGTYP', src.get('VGTYP', 7)))
        if vgtyp < 1:
            print(f'  WARNING: GRIDCRO2D VGTYP={vgtyp} is invalid, falling back to 7 (sigma)')
            vgtyp = 7

        overrides = {
            'SDATE': np.int32(sdate),
            'STIME': np.int32(stime),
            'TSTEP': np.int32(tstep_val),
            'NCOLS': np.int32(COL),
            'NROWS': np.int32(ROW),
            'NLAYS': np.int32(lay),
            'NVARS': np.int32(n_species),
            'VGTYP': np.int32(vgtyp),
            'GDNAM': 'CMAQ Emissions',
            'UPNAM': 'ISAT',
            'FILEDESC': 'Chao Gao',
            'HISTORY': ' ',
            'VAR-LIST': varl,
        }

        now = datetime.now()
        cdate = now.year * 1000 + int(now.strftime('%j'))
        ctime = now.hour * 10000 + now.minute * 100 + now.second
        fallbacks = {
            'IOAPI_VERSION': 'ioapi-3.2: $Id: init3.F90 247 2023-03-22 15:59:19Z coats $'.ljust(80),
            'EXEC_ID': 'SEI'.ljust(80),
            'FTYPE': np.int32(1),
            'CDATE': np.int32(cdate),
            'CTIME': np.int32(ctime),
            'WDATE': np.int32(cdate),
            'WTIME': np.int32(ctime),
            'NTHIK': np.int32(1),
            'GDTYP': np.int32(2),
            'P_ALP': np.float64(25.0),
            'P_BET': np.float64(47.0),
            'P_GAM': np.float64(105.0),
            'XCENT': np.float64(105.0),
            'YCENT': np.float64(40.0),
            'XORIG': np.float64(0.0),
            'YORIG': np.float64(0.0),
            'XCELL': np.float64(1000.0),
            'YCELL': np.float64(1000.0),
            'VGTOP': np.float32(5000.0),
            'VGLVLS': np.array([1.0, 0.993], dtype=np.float32),
        }

        for name in _IOAPI_ATTR_ORDER:
            if name in overrides:
                value = overrides[name]
            elif name in src:
                value = src[name]
            elif name in fallbacks:
                value = fallbacks[name]
            else:
                continue
            try:
                root.setncattr(name, value)
            except Exception:
                pass