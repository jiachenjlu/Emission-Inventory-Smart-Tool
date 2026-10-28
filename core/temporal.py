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

    def build_temporal_matrix(self, month_idx, source_key, n_days=None):
        monthly_f = self.get_monthly_factors(source_key)
        weekly_f = self.get_weekly_factors(source_key)
        hourly_f = self.get_hourly_factors(source_key)

        if n_days is None:
            n_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month_idx]

        month_factor = monthly_f[month_idx] if month_idx < len(monthly_f) else 1.0

        hourly_matrix = np.zeros((n_days, 24))
        for d in range(n_days):
            wd = d % 7
            hour_factor = weekly_f[wd] * hourly_f
            hourly_matrix[d, :] = month_factor * hour_factor

        total = hourly_matrix.sum()
        if total > 0:
            hourly_matrix = hourly_matrix / total * 12.0

        return hourly_matrix.flatten()

    def build_temporal_matrix_range(self, start_dt, end_dt, source_key):
        from datetime import timedelta

        monthly_f = self.get_monthly_factors(source_key)
        weekly_f = self.get_weekly_factors(source_key)
        hourly_f = self.get_hourly_factors(source_key)

        n_hours = int((end_dt - start_dt).total_seconds() / 3600) + 1
        factors = np.zeros(n_hours, dtype=np.float64)

        for h in range(n_hours):
            cur = start_dt + timedelta(hours=h)
            m_idx = cur.month - 1
            w_idx = cur.weekday()
            hr_idx = cur.hour

            month_factor = monthly_f[m_idx] if m_idx < len(monthly_f) else 1.0
            factors[h] = month_factor * weekly_f[w_idx] * hourly_f[hr_idx]

        total = factors.sum()
        if total > 0:
            n_months_span = (end_dt.year - start_dt.year) * 12 + end_dt.month - start_dt.month + 1
            factors = factors / total * (12.0 if n_months_span <= 1 else float(n_months_span) * 12.0 / n_months_span)

        return factors