import numpy as np
import netCDF4 as nc
from pathlib import Path


class MEICReader:
    NODATA_VALUE = -9999.0

    def __init__(self, nc_path):
        self.nc_path = Path(nc_path)
        self.ds = None
        self.lat_grid = None
        self.lon_grid = None
        self.nodata = -9999.0
        self._open()

    def _open(self):
        self.ds = nc.Dataset(str(self.nc_path), 'r')
        x_range = self.ds.variables['x_range'][:]
        y_range = self.ds.variables['y_range'][:]
        spacing = self.ds.variables['spacing'][:]
        dimension = self.ds.variables['dimension'][:]

        try:
            self.nodata = float(getattr(self.ds.variables['z'], 'nodata_value', -9999.0))
        except:
            self.nodata = -9999.0

        self.lon_res = spacing[0]
        self.lat_res = spacing[1]
        self.nx = int(dimension[0])
        self.ny = int(dimension[1])

        lon_center = np.linspace(
            x_range[0] + spacing[0] / 2,
            x_range[1] - spacing[0] / 2,
            self.nx
        )
        lat_center = np.linspace(
            y_range[0] + spacing[1] / 2,
            y_range[1] - spacing[1] / 2,
            self.ny
        )

        self.lon_grid, self.lat_grid = np.meshgrid(lon_center, lat_center)
        self.lon_flat = self.lon_grid.flatten()
        self.lat_flat = self.lat_grid.flatten()

    @property
    def n_grids(self):
        return self.nx * self.ny

    def get_data(self):
        z = self.ds.variables['z'][:]
        z = np.array(z, dtype=np.float64)
        z[z <= self.nodata] = 0.0
        return z

    def get_data_raw(self):
        z = self.ds.variables['z'][:]
        return np.array(z, dtype=np.float64)

    def get_coords_flat(self):
        return self.lon_flat, self.lat_flat

    def get_valid_mask(self):
        z = self.ds.variables['z'][:]
        return z > self.nodata

    def close(self):
        if self.ds:
            self.ds.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
