from pathlib import Path

PROJECT_ROOT = Path(r"D:\ai agent\智能清单工具")

DATA_ROOT = PROJECT_ROOT / "data"
INPUT_DIR = DATA_ROOT / "inputs"
TEMPLATE_DIR = DATA_ROOT / "templates"
OUTPUT_DIR = DATA_ROOT / "outputs"

MEIC_RESOLUTION = 0.25

WGS84_CRS = "EPSG:4326"

LCC_CMAQ = "+proj=lcc +lat_1=15 +lat_2=52.5 +lat_0=47.2973977553865 +lon_0=125.336730559849 +x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs"

LANDUSE_FARM = [11, 12]
LANDUSE_INDUSTRY = [53]
LANDUSE_URBAN = [51]

SOURCES = ["AG", "IN", "PP", "AR", "TR"]
SOURCE_NAMES = {
    "AG": "agriculture", "IN": "industry", "PP": "power",
    "AR": "residential", "TR": "transportation",
}
SOURCE_PROFILE_KEY = {
    "AG": "AG", "IN": "IN", "PP": "PP", "AR": "AR", "TR": "TR",
}