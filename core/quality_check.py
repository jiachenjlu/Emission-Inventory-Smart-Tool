import numpy as np
import pandas as pd


def run_quality_check(emissions_all, meic_totals):
    results = []
    print('=== Quality Check ===')

    if 'PP' in emissions_all:
        pp = emissions_all['PP']
        if 'NH3' in pp.columns:
            nh3_total = pp['NH3'].sum()
            passed = nh3_total < 1e-6
            results.append(('Power NH3=0', passed, f'NH3={nh3_total:.4e}'))
            print(f'  [{"PASS" if passed else "FAIL"}] Power NH3=0: {nh3_total:.4e}')

    all_cols = set()
    for src, df in emissions_all.items():
        all_cols.update(df.columns)

    if 'PM25' in all_cols and 'PM10' in all_cols:
        pm25_total = sum(emissions_all[s]['PM25'].sum() for s in emissions_all if 'PM25' in emissions_all[s].columns)
        pm10_total = sum(emissions_all[s]['PM10'].sum() for s in emissions_all if 'PM10' in emissions_all[s].columns)
        passed = pm25_total <= pm10_total * 1.001
        results.append(('PM25<=PM10', passed, f'PM25={pm25_total:.4e}, PM10={pm10_total:.4e}'))
        print(f'  [{"PASS" if passed else "FAIL"}] PM25<=PM10: {pm25_total:.4e} <= {pm10_total:.4e}')

    for pollutant, orig_total in meic_totals.items():
        alloc_total = 0
        for src, df in emissions_all.items():
            if pollutant in df.columns:
                alloc_total += df[pollutant].sum()
        if orig_total > 0:
            ratio = alloc_total / orig_total
            passed = 0.8 < ratio < 1.2
            results.append((f'{pollutant} mass balance', passed, f'alloc/orig={ratio:.3f}'))
            print(f'  [{"PASS" if passed else "WARN"}] {pollutant}: ratio={ratio:.3f}')

    print('=== Check Done ===')
    return results
