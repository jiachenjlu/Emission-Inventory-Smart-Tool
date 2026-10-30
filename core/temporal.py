import pandas as pd
import numpy as np
from pathlib import Path


class TemporalProfile:
    def __init__(self, template_dir):
        self.template_dir = Path(template_dir)
        self.hourly = None
        self.weekly = None
        self.monthly = None
        self._load()

    def _load(self):
        hourly_path = self.template_dir / 'hourly.csv'
        if hourly_path.exists():
            df = pd.read_csv(hourly_path)
            self.hourly = df.set_index(df.columns[0])

        weekly_path = self.template_dir / 'weekly.csv'
        if weekly_path.exists():
            df = pd.read_csv(weekly_path)
            self.weekly = df.set_index(df.columns[0])

        monthly_path = self.template_dir / 'monthly.csv'
        if monthly_path.exists():
            df = pd.read_csv(monthly_path)
            self.monthly = df.set_index(df.columns[0])

    def get_hourly_factors(self, source_key):
        if self.hourly is None or source_key not in self.hourly.columns:
            return np.ones(24) / 24
        return self.hourly[source_key].values

    def get_weekly_factors(self, source_key):
        if self.weekly is None or source_key not in self.weekly.columns:
            return np.ones(7) / 7
        return self.weekly[source_key].values

    def get_monthly_factors(self, source_key):
        if self.monthly is None or source_key not in self.monthly.columns:
            return np.ones(12) / 12
        idx = self.monthly.index.tolist()
        vals = self.monthly[source_key].values
        month_idx_map = {int(idx[i]): i for i in range(len(idx))}
        return vals

    def build_temporal_matrix(self, month_idx, source_key, n_days=None, inputtype='month', year=None):
        from datetime import datetime, timedelta

        if year is None:
            year = datetime.now().year
        if n_days is None:
            n_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month_idx]
            if month_idx == 1 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
                n_days = 29

        start_dt = datetime(year, month_idx + 1, 1, 0)
        end_dt = start_dt + timedelta(hours=n_days * 24 - 1)
        return self.build_temporal_matrix_range(
            start_dt, end_dt, source_key, inputtype=inputtype
        )

    def build_temporal_matrix_range(self, start_dt, end_dt, source_key, inputtype='month'):
        from datetime import timedelta

        monthly_f = self.get_monthly_factors(source_key)
        weekly_f = self.get_weekly_factors(source_key)
        hourly_f = self.get_hourly_factors(source_key)

        n_hours = int((end_dt - start_dt).total_seconds() / 3600) + 1
        factors = np.zeros(n_hours, dtype=np.float64)
        month_idx = np.zeros(n_hours, dtype=np.int32)

        for h in range(n_hours):
            cur = start_dt + timedelta(hours=h)
            month_idx[h] = cur.month - 1
            factors[h] = weekly_f[cur.weekday()] * hourly_f[cur.hour]

        for m_idx in np.unique(month_idx):
            mask = month_idx == m_idx
            total = factors[mask].sum()
            if total <= 0:
                continue
            if str(inputtype).strip().lower() == 'year':
                scale = monthly_f[m_idx] if m_idx < len(monthly_f) else 1.0
            else:
                scale = 1.0
            factors[mask] = factors[mask] / total * scale

        return factors