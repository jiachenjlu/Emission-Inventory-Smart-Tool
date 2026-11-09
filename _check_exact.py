import numpy as np, pandas as pd, sys, datetime, calendar
sys.path.insert(0, '.')
from core.temporal import TemporalProfile

hourly = pd.read_csv(r'D:\ai agent\智能清单工具\data\templates\hourly.csv')
weekly = pd.read_csv(r'D:\ai agent\智能清单工具\data\templates\weekly.csv')
monthly = pd.read_csv(r'D:\ai agent\智能清单工具\data\templates\monthly.csv')

year, month, src = 2025, 6, 'IN'
days = calendar.monthrange(year, month)[1]

isat_f = []
for day in range(1, days + 1):
    ws = []
    for d in range(1, days + 1):
        ws.append(weekly.loc[weekly['weekly'] == float(datetime.datetime(year, month, d).weekday())][src].mean())
    wsn = np.array(ws) / np.array(ws).sum()
    mf = monthly.loc[monthly['monthly'] == float(month)][src].mean()
    for hr in range(24):
        hf = hourly.loc[hourly['hourly'] == float(hr)][src].mean()
        isat_f.append(mf * wsn[day - 1] * hf)
isat_f = np.array(isat_f)

tp = TemporalProfile(r'D:\ai agent\智能清单工具\data\templates')
our_f = tp.build_temporal_matrix_range(datetime.datetime(2025, 6, 1, 0), datetime.datetime(2025, 6, 30, 23), 'IN', inputtype='month')

print('ISAT.M temporal sum (June IN):', isat_f.sum())
print('Our temporal sum (June IN):   ', our_f.sum())
print('Ratio ISAT.M/Ours:', isat_f.sum() / our_f.sum())
mf_val = monthly.loc[monthly['monthly'] == 6]['IN'].mean()
print('monthfactor June IN:', mf_val)
print()

# Now let's trace the EXACT computation path for a hypothetical value
# Assume MEIC gives 100 ton/month of SO2 for one grid cell in June
meic_val = 100.0  # ton/month

print('=' * 70)
print('  EXACT COMPUTATION: MEIC 100 ton/month SO2, one cell, June 1st hour 0')
print('=' * 70)

# ISAT.M path (assuming CSV contains annual data)
# In ISAT.M, the ArcGIS step sums all 12 months to get annual total
# annual_val = sum of MEIC monthly values for all 12 months
# For simplicity, assume uniform: annual_val = meic_val * 12
annual_val = meic_val * 12  # ton/year (simplified)
print(f'\nISAT.M path (CSV = annual = {annual_val} ton/year):')
speciate_in = pd.read_csv(r'D:\ai agent\智能清单工具\data\templates\speciate_IN.csv')
so2_row = speciate_in[speciate_in['pollutant'] == 'SO2']
print(f'  SO2 speciate rows: {len(so2_row)}')
for _, row in so2_row.iterrows():
    sp = row['species']
    sf = row['split_factor']
    div = row['divisor']
    unit = row.get('unit', 'moles/s')
    # ISAT.M formula for hour 0 of June 1
    isat_val = annual_val * sf * 1e6 * isat_f[0] / div / 3600
    print(f'    {sp}: {annual_val} * {sf} * 1e6 * {isat_f[0]:.10f} / {div} / 3600 = {isat_val:.6e} {unit}')

# Our path (MEIC = monthly data)
print(f'\nOur path (MEIC = monthly = {meic_val} ton/month):')
for _, row in so2_row.iterrows():
    sp = row['species']
    sf = row['split_factor']
    div = row['divisor']
    unit = row.get('unit', 'moles/s')
    # Our formula
    speciated = meic_val * sf * 1e6 / div  # speciate step
    nc_val = speciated * our_f[0] / 3600  # temporal + /3600
    print(f'    {sp}: {meic_val} * {sf} * 1e6 / {div} * {our_f[0]:.10f} / 3600 = {nc_val:.6e} {unit}')

# Compare
print(f'\nRatio (Ours / ISAT.M) for SO2->SO2:')
isat_so2 = annual_val * 1.0 * 1e6 * isat_f[0] / 64 / 3600
our_so2 = meic_val * 1.0 * 1e6 / 64 * our_f[0] / 3600
print(f'  {our_so2 / isat_so2:.6f}')
print(f'  = (meic_val * our_f[0]) / (annual_val * isat_f[0])')
print(f'  = (meic_val * our_f[0]) / (meic_val * 12 * isat_f[0])')
print(f'  = our_f[0] / (12 * isat_f[0])')
print(f'  = {our_f[0] / (12 * isat_f[0]):.6f}')

print()
print('=' * 70)
print('  KEY INSIGHT')
print('=' * 70)
print()
print('If ISAT.M CSV = annual total (sum of 12 months):')
print('  ISAT.M: annual * monthfactor * week*hour * 1e6 / div / 3600')
print('  Ours:   monthly * (week*hour/sum) * 1e6 / div / 3600')
print()
print('  If annual = monthly * 12 (uniform months):')
print('  ISAT.M: monthly*12 * monthfactor * week*hour * 1e6 / div / 3600')
print('  Ours:   monthly * (week*hour/sum) * 1e6 / div / 3600')
print()
print('  Ratio = Ours/ISAT.M = (week*hour/sum) / (12 * monthfactor * week*hour)')
print('         = 1 / (12 * monthfactor * sum)')
print('         where sum = sum of week*hour over all hours in month')
print()
print('  But wait - in ISAT.M, weekfactor is already normalized (weeksumsing),')
print('  and hourfactor sums to 1 per day.')
print('  So sum of (weekfactor * hourfactor) over month = sum of weeksumsing = 1.0')
print('  Therefore ISAT.M temporal for one hour = monthfactor * weeksumsing * hourly')
print('  And sum over month = monthfactor')
print()
print('  Our temporal for one hour = (weekly*hourly) / sum(weekly*hourly)')
print('  Sum over month = 1.0')
print()
print('  So: ISAT.M hour factor = monthfactor * (weekly/sum_weekly) * hourly')
print('      Our hour factor    = (weekly * hourly) / sum(weekly * hourly over month)')
print()
print('  These are DIFFERENT distributions within the month!')
print('  ISAT.M: week and hour are independent (product of separate normalizations)')
print('  Ours:   week and hour are jointly normalized')

# Verify this
print()
print('Checking if ISAT.M week*hour == our week*hour (up to monthfactor):')
ratio_per_hour = isat_f / np.where(our_f > 0, our_f, 1)
print(f'  Ratio range: {ratio_per_hour.min():.10f} to {ratio_per_hour.max():.10f}')
print(f'  Is ratio constant? {np.allclose(ratio_per_hour, ratio_per_hour.mean(), rtol=1e-6)}')
print(f'  Mean ratio: {ratio_per_hour.mean():.10f}')
print(f'  monthfactor: {mf_val:.10f}')
print(f'  Ratio == monthfactor? {np.isclose(ratio_per_hour.mean(), mf_val, rtol=1e-4)}')