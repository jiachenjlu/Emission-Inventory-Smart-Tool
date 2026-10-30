import os
import sys
import argparse
import configparser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.pipeline import run_pipeline


INI_PATH = Path(__file__).resolve().parent / 'config.ini'


def load_ini():
    cp = configparser.ConfigParser()
    defaults = {
        'meic_nc_dir': '',
        'cmaq_grid': '',
        'gridcro2d': '',
        'landuse': '',
        'population': '',
        'roads': '',
        'template_dir': '',
        'output_dir': '',
        'start_time': '2020-01-01-00',
        'end_time': '2020-01-31-23',
        'meic_year': '',
        'meic_month': '',
        'inputtype': 'month',
        'sources': 'AG,IN,PP,AR,TR',
    }
    if INI_PATH.exists():
        cp.read(INI_PATH, encoding='utf-8')
        if cp.has_section('PATHS'):
            for k in defaults:
                if cp.has_option('PATHS', k):
                    defaults[k] = cp.get('PATHS', k).strip()
        if cp.has_section('RUN'):
            for k in ['start_time', 'end_time', 'meic_year', 'meic_month', 'inputtype', 'sources']:
                if cp.has_option('RUN', k):
                    defaults[k] = cp.get('RUN', k).strip()
    return defaults


def main():
    ini = load_ini()

    parser = argparse.ArgumentParser(
        description='Smart Emission Inventory Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
直接运行 (使用 config.ini):
  python run.py

命令行覆盖 INI 配置:
  python run.py --start_time 2025-07-01-00 --end_time 2025-07-31-23 --sources AG,IN,PP,AR,TR

时间格式: YYYY-MM-DD-HH (如 2025-06-01-00 表示2025年6月1日0时)
INI 文件位置: config.ini
        ''',
    )
    parser.add_argument('--ini', type=str, default=str(INI_PATH),
                        help='配置文件路径 (默认 config.ini)')
    parser.add_argument('--meic', type=str, default=ini['meic_nc_dir'])
    parser.add_argument('--grid', type=str, default=ini['cmaq_grid'])
    parser.add_argument('--gridcro2d', type=str, default=ini['gridcro2d'])
    parser.add_argument('--landuse', type=str, default=ini['landuse'])
    parser.add_argument('--pop', type=str, default=ini['population'])
    parser.add_argument('--roads', type=str, default=ini['roads'])
    parser.add_argument('--templates', type=str, default=ini['template_dir'])
    parser.add_argument('--output', type=str, default=ini['output_dir'])
    parser.add_argument('--start_time', type=str, default=ini['start_time'],
                        help='起始时间 YYYY-MM-DD-HH (如 2025-06-01-00)')
    parser.add_argument('--end_time', type=str, default=ini['end_time'],
                        help='结束时间 YYYY-MM-DD-HH (如 2025-06-30-23)')
    parser.add_argument('--meic_year', type=int, default=None,
                        help='MEIC数据年份 (如 2020，默认取start_time年份)')
    parser.add_argument('--meic_month', type=int, default=None,
                        help='MEIC数据起始月份 (如 6，默认取start_time月份)')
    parser.add_argument('--sources', type=str, default=ini['sources'])
    parser.add_argument('--inputtype', type=str, default=ini['inputtype'],
                        choices=['month', 'year'],
                        help='排放清单输入时间尺度: month(月总量) / year(年总量)')
    args = parser.parse_args()

    from datetime import datetime as _dt
    start_dt = _dt.strptime(args.start_time, '%Y-%m-%d-%H')
    end_dt = _dt.strptime(args.end_time, '%Y-%m-%d-%H')

    meic_year = args.meic_year
    if meic_year is None:
        if ini['meic_year']:
            meic_year = int(ini['meic_year'])
        else:
            meic_year = start_dt.year

    meic_month = args.meic_month
    if meic_month is None:
        if ini['meic_month']:
            meic_month = int(ini['meic_month'])
        else:
            meic_month = start_dt.month

    sources = [s.strip() for s in args.sources.split(',')]

    print('Run config (from {}):'.format(Path(args.ini).name))
    print(f'  meic_nc_dir : {args.meic}')
    print(f'  cmaq_grid   : {args.grid}')
    print(f'  gridcro2d   : {args.gridcro2d}')
    print(f'  landuse     : {args.landuse}')
    print(f'  population  : {args.pop}')
    print(f'  roads       : {args.roads}')
    print(f'  template_dir: {args.templates}')
    print(f'  output_dir  : {args.output}')
    print(f'  start_time={start_dt.strftime("%Y-%m-%d %H:00")}, '
          f'end_time={end_dt.strftime("%Y-%m-%d %H:00")}')
    print(f'  meic_year={meic_year}, meic_month={meic_month}, sources={sources}')
    print(f'  inputtype={args.inputtype}')
    print()

    gridcro2d_path = args.gridcro2d if args.gridcro2d else None
    if gridcro2d_path and not os.path.isabs(gridcro2d_path):
        gridcro2d_path = str(Path(__file__).resolve().parent / gridcro2d_path)

    run_pipeline(
        meic_nc_dir=args.meic,
        cmaq_grid_file=args.grid,
        landuse_file=args.landuse,
        pop_file=args.pop,
        roads_file=args.roads,
        template_dir=args.templates,
        output_dir=args.output,
        start_dt=start_dt,
        end_dt=end_dt,
        meic_year=meic_year,
        meic_month=meic_month,
        sources=sources,
        gridcro2d_file=gridcro2d_path,
        inputtype=args.inputtype,
    )


if __name__ == '__main__':
    main()