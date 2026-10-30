import pandas as pd
import numpy as np
from pathlib import Path

MEIC_TO_CSV_POLLUTANT = {
    'SO2': 'SO2',
    'NOx': 'NOX',
    'CO': 'CO',
    'NH3': 'NH3',
    'PM25': 'PM25',
    'PM10': 'PMC',
    'VOC': 'TOG',
    'BC': 'BC',
    'OC': 'OC',
}


class SpeciationEngine:
    def __init__(self, template_dir):
        self.template_dir = Path(template_dir)
        self.mappings = {}

    def load_speciate_csv(self, source):
        fname = self.template_dir / f'speciate_{source}.csv'
        if not fname.exists():
            print(f'  Warning: {fname} not found, skipping speciation for {source}')
            return None
        df = pd.read_csv(fname)
        self.mappings[source] = df
        return df

    def species_order(self, source):
        mapping = self.mappings.get(source)
        if mapping is None:
            return []
        order = []
        for sp in mapping['species']:
            sp = str(sp)
            if sp not in order:
                order.append(sp)
        return order

    def _row_unit(self, row):
        unit = str(row.get('unit', '')).strip().lower()
        if unit in ('g/s', 'moles/s', 'mol/s'):
            return 'g/s' if unit == 'g/s' else 'moles/s'
        pollutant = str(row['pollutant']).strip().upper()
        if pollutant in ('PM25', 'PMC'):
            return 'g/s'
        return 'moles/s'

    def species_units(self, source):
        mapping = self.mappings.get(source)
        if mapping is None:
            return None
        units = {}
        for _, row in mapping.iterrows():
            units[str(row['species'])] = self._row_unit(row)
        return units

    def speciate(self, emissions_df, source):
        if source not in self.mappings or self.mappings[source] is None:
            return emissions_df.copy()

        mapping = self.mappings[source]
        species_order = self.species_order(source)
        if not species_order:
            return pd.DataFrame(index=emissions_df.index, dtype=np.float64)

        result = pd.DataFrame(
            0.0, index=emissions_df.index, columns=species_order, dtype=np.float64
        )

        for meic_col in emissions_df.columns:
            csv_pollutant = MEIC_TO_CSV_POLLUTANT.get(meic_col, meic_col)

            subset = mapping[mapping['pollutant'] == csv_pollutant]
            if len(subset) == 0:
                continue

            for _, row in subset.iterrows():
                species = str(row['species'])
                split = float(row['split_factor'])
                divisor = float(row['divisor']) if 'divisor' in row.index else 1.0
                if not np.isfinite(divisor) or divisor <= 0:
                    divisor = 1.0

                conv = split * 1e6
                if self._row_unit(row) != 'g/s':
                    conv = conv / divisor

                result[species] = (
                    result[species].values
                    + emissions_df[meic_col].fillna(0).values * conv
                )

        result = result.fillna(0)
        return result

    def load_all(self, sources):
        for s in sources:
            self.load_speciate_csv(s)