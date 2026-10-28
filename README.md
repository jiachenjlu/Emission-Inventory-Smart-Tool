# Smart Emission Inventory Tool (SEI)

基于纯 Python 的 CMAQ 排放清单制作工具，替代 ArcGIS + ISAT.M 工作流。

## 工作流程

`
MEIC 全国排放数据 + CMAQ 网格 + 代理数据 (土地利用/人口/路网)
                         |
                         v
   +-----------------------------------------+
   |  Stage 1  Grid Setup                    |  读取 MEIC/CMAQ 网格
   |  Stage 2  Grid Intersection             |  MEIC x CMAQ 碎格求交
   |  Stage 3  MEIC Data Loading             |  按污染物读取 MEIC NC
   |  Stage 4  Spatial Allocation            |  按代理变量分配到 CMAQ 网格
   |  Stage 5  Speciation                    |  基础污染物 -> CMAQ 物种
   |  Stage 6  Temporal Profile              |  月 -> 小时时间廓线
   |  Stage 7  Quality Check                 |  质量检查
   |  Stage 8  Write IOAPI NC                |  输出 CMAQ 可用 NC 文件
   +-----------------------------------------+
                         |
                         v
          CMAQ 兼容 IOAPI NetCDF 文件 (小时分辨率, 近地面)
`

## 项目结构

`
智能清单工具/
+-- run.py                     # 命令行入口
+-- config/
|   +-- settings.py            # 全局配置 (投影/土地利用编码/排放源映射)
+-- core/
|   +-- pipeline.py            # 主流程编排
|   +-- meic_reader.py         # MEIC netCDF 读取 (nodata=-9999 过滤)
|   +-- grid_builder.py        # 网格构建与重投影
|   +-- spatial_intersect.py   # 空间求交 + 按面积/长度/点数分配
|   +-- speciate.py            # 物种分解 (长表 CSV 配置)
|   +-- temporal.py            # 时间廓线 (月/周/小时 三维合并)
|   +-- nc_writer.py           # IOAPI NC 写入 (SDATE=YYYYDDD)
|   +-- quality_check.py       # 质量检查
+-- data/
    +-- inputs/                # 输入数据放这里
    +-- templates/             # 配置模板
        +-- speciate_*.csv     # 物种分配表 (修改即可改变分配方式)
        +-- hourly.csv         # 小时廓线 (24行 x 排放源)
        +-- weekly.csv         # 周廓线 (7行 x 排放源)
        +-- monthly.csv        # 月廓线 (12行 x 排放源)
`

## 排放源与代理变量

| 排放源 | 代码 | 代理变量 | 分配方式 |
|--------|------|----------|----------|
| 农业 | AG | 土地利用 (农田) | 面积比 |
| 工业 | IN | 土地利用 (工业) | 面积比 |
| 电力 | PP | 土地利用 (城市/建成区) | 面积比 |
| 居民 | AR | 人口分布 | 点数/权重 |
| 交通 | TR | 路网 | 长度比 |

修改 config/settings.py 中的 LANDUSE_FARM / LANDUSE_INDUSTRY / LANDUSE_URBAN 可改变土地利用编码映射。

## 物种分配方式

物种分解完全由 data/templates/speciate_*.csv 控制，格式为长表：

`csv
pollutant,species,split_factor,divisor,mass_fraction
TOG,ALD2,0.0177,46.7520,0.0177
TOG,ALDX,0.0208,38.6021,0.0208
NOX,HONO,0.0080,46.0000,0.0080
CO,CO,1.0000,28.0000,1.0000
`

- 修改 split_factor 即可调整分配比例
- MEIC 污染物名与 CSV 列名的映射在 core/speciate.py 的 MEIC_TO_CSV_POLLUTANT 中

## 时间分辨率

最终输出为小时分辨率。时间廓线由三层合并：

monthly_factor[month] x weekly_factor[day_of_week] x hourly_factor[hour]

修改 data/templates/ 下的 monthly.csv / weekly.csv / hourly.csv 可调整时间廓线。

## 依赖

`
numpy >= 1.24
pandas >= 2.0
geopandas >= 0.14
shapely >= 2.0
netCDF4 >= 1.6
pyproj >= 3.6
`

## 使用方法

### 方式 1：命令行

`ash
python run.py ^
  --meic D:\ai_agent_data\MEIC2020 ^
  --grid D:\ai_agent_data\CMAQ\aqm_d01.shp ^
  --landuse D:\ai_agent_data\Landuse\土地利用数据.shp ^
  --pop D:\ai_agent_data\Pop\pop2021.shp ^
  --roads D:\ai_agent_data\Roads\gis_osm_roads_free_1.shp ^
  --templates data\templates ^
  --output D:\ai_agent_data\output_202001.nc ^
  --year 2020 --month 1 ^
  --sources AG,IN,PP,AR,TR
`

### 方式 2：Python API

`python
from core.pipeline import run_pipeline

run_pipeline(
    meic_nc_dir=r'D:\ai_agent_data\MEIC2020',
    cmaq_grid_file=r'D:\ai_agent_data\CMAQ\aqm_d01.shp',
    landuse_file=r'D:\ai_agent_data\Landuse\土地利用数据.shp',
    pop_file=r'D:\ai_agent_data\Pop\pop2021.shp',
    roads_file=r'D:\ai_agent_data\Roads\gis_osm_roads_free_1.shp',
    template_dir=r'data\templates',
    output_nc=r'D:\ai_agent_data\output_202001.nc',
    year=2020,
    month=1,
    sources=['AG', 'IN', 'PP', 'AR'],
)
`

### 批量制作（多个月份）

`python
from core.pipeline import run_pipeline

for month in range(1, 13):
    run_pipeline(
        ..., year=2020, month=month,
        output_nc=rf'D:\ai_agent_data\output_2020{month:02d}.nc',
        ...,
    )
`

## MEIC 数据格式

MEIC netCDF 文件命名规则：{year}_{month:02d}_{source}_{pollutant}.nc

`
2020_01_agriculture_SO2.nc
2020_01_industry_NOx.nc
...
`

NC 文件内部变量：x_range, y_range, spacing, dimension, z (nodata=-9999)

## 输出 NC 规格（IOAPI 兼容）

| 属性 | 值 |
|------|-----|
| SDATE | YYYYDDD (儒略日) |
| STIME | 0 (HHMMSS) |
| TSTEP | 1 (小时) |
| NLAYS | 1 (近地面) |
| NROWS x NCOLS | 自动根据 CMAQ 网格计算 |
| TSTEP 数 | 自动 = 当月天数 x 24 |
| 变量格式 | (TSTEP, LAY, ROW, COL) |
| 单位 | PM 类 = g/s, 其余 = moles/s |
| TFLAG | (TSTEP, 1, 2) -- YYYYDDD & HHMMSS |

## 质量检查项

- **电力源 NH3 = 0**: 检验电力源是否正确 (电力不应排放 NH3)
- **PM25 <= PM10**: 颗粒物质量关系
- **质量平衡比例**: 分配后总量 / 原始 MEIC 总量 (WARN 只在 CMAQ 覆盖全国一小部分时出现, 属正常)

## 已知限制

- **TR (交通源)** 需要完整路网 Shapefile (.shp + .shx + .dbf + .prj)
- **垂直层** 当前只支持 1 层 (近地面), 扩展多层需增加垂直分配模块
- **MEIC nodata** 硬编码为 -9999.0 (可在 meic_reader.py 中修改)

## 参考

- MEIC 模型: http://www.meicmodel.org
- ISAT.M: 基于 ArcGIS 的排放清单空间分配工具
- IOAPI NetCDF: CMAQ/WRF 等模式的标准输入格式
