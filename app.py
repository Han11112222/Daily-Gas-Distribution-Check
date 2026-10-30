import streamlit as st
import pandas as pd
import numpy as np
import io
import re
import matplotlib as mpl
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────
# [0] 페이지 기본 설정
# ─────────────────────────────────────────────────────────
st.set_page_config(page_title="도시가스 통합 관리 시스템", layout="wide")

# [스타일] CSS 적용
st.markdown("""
   <style>
   div[data-testid="stMetric"] {
       background-color: #F0F2F6;
       border-radius: 10px;
       padding: 15px;
       min-height: 200px;
       display: flex;
       flex-direction: column;
       justify-content: center;
    }
   </style>
""", unsafe_allow_html=True)

def set_korean_font():
    ttf = Path(__file__).parent / "NanumGothic-Regular.ttf"
    if ttf.exists():
        try:
            mpl.font_manager.fontManager.addfont(str(ttf))
            mpl.rcParams["font.family"] = "NanumGothic"
            mpl.rcParams["axes.unicode_minus"] = False
        except Exception:
            pass
set_korean_font()

# 가정용 청구전수 월별총계 (단위: 전) — (연, 월): 값
# 다른 월·연도 자료가 생기면 아래에 한 줄씩 추가하세요. (예: (2026, 10): 1200000)
HOUSEHOLD_MONTHLY = {
    (2016, 10): 975242,
    (2017, 10): 1011921,
    (2018, 10): 1050535,
    (2019, 10): 1079111,
    (2020, 10): 1094948,
    (2021, 10): 1115881,
    (2022, 10): 1137543,
    (2023, 10): 1154516,
    (2024, 10): 1170260,
    (2025, 10): 1186038,
    (2026, 9): 1197445,
}

def household_total(year, month):
    """선택 연·월의 가정용 청구전수(월별총계)를 (값, 실제 사용한 (연, 월))로 반환.
    아직 집계되지 않은 최신 시점(예: 2026년 10월)은 가장 최근 월 값으로 대체하고,
    과거 시점의 누락은 NaN으로 처리한다."""
    key = (int(year), int(month))
    if key in HOUSEHOLD_MONTHLY:
        return HOUSEHOLD_MONTHLY[key], key
    last = max(HOUSEHOLD_MONTHLY)
    has_month = any(k[1] == key[1] for k in HOUSEHOLD_MONTHLY)
    if has_month and key > last:
        return HOUSEHOLD_MONTHLY[last], last
    return np.nan, None

# ─────────────────────────────────────────────────────────
# [NEW] 기상청 API 호출 함수 (대구: 143)
# ─────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)  # 1시간마다 갱신
def get_daegu_temperature(target_date_str):
    """
    공공데이터포털 기상청 종관기상관측(ASOS) API를 통해 대구(143)의 평균기온을 가져옵니다.
    target_date_str: 'YYYYMMDD' 형식 (예: '20260126')
    """
    API_KEY = "YPnuBBk5fCP55U/+PF8HS2ifcwDclA2+WghIxuodBYRwi58ONaiMm8ATkzzaZSk1nP3dfXBFfEGboryZuZy9IQ=="

    url = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
    params = {
        "serviceKey": API_KEY,
        "pageNo": "1",
        "numOfRows": "10",
        "dataType": "JSON",
        "dataCd": "ASOS",
        "dateCd": "DAY",
        "startDt": target_date_str,
        "endDt": target_date_str,
        "stnIds": "143"  # 143: 대구 지점 코드
    }

    try:
        response = requests.get(url, params=params)
        data = response.json()
        items = data['response']['body']['items']['item']
        if items:
            avg_temp = float(items[0]['avgTa'])
            return avg_temp
    except Exception as e:
        return None
    return None

# ─────────────────────────────────────────────────────────
# [NEW] 기상청 API: 대구(143) 월간 일별 최저기온 (연·월 단위 1회 호출)
# ─────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=3600)
def get_daegu_month_temps(year: int, month: int):
    """
    ASOS 일자료에서 대구(143)의 해당 연·월 일별 최저기온을 가져옵니다.
    반환: DataFrame(일, 최저기온) 또는 None
    """
    import calendar
    API_KEY = "YPnuBBk5fCP55U/+PF8HS2ifcwDclA2+WghIxuodBYRwi58ONaiMm8ATkzzaZSk1nP3dfXBFfEGboryZuZy9IQ=="
    last_day = calendar.monthrange(year, month)[1]
    url = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
    params = {
        "serviceKey": API_KEY,
        "pageNo": "1",
        "numOfRows": "40",
        "dataType": "JSON",
        "dataCd": "ASOS",
        "dateCd": "DAY",
        "startDt": f"{year}{month:02d}01",
        "endDt": f"{year}{month:02d}{last_day:02d}",
        "stnIds": "143",
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        items = data['response']['body']['items']['item']
        rows = []
        for it in items:
            rows.append({
                "일": pd.to_datetime(it['tm']).day,
                "최저기온": pd.to_numeric(it.get('minTa'), errors='coerce'),
            })
        out = pd.DataFrame(rows)
        return out if not out.empty else None
    except Exception:
        return None

# ─────────────────────────────────────────────────────────
# [공통 함수 1] 실적 데이터 로드 (구글시트 -> 엑셀 -> 기온API 결합)
# ─────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=600)
def load_historical_data_common():
    sheet_id = "13HrIz6OytYDykXeXzXJ02I6XbaKin1YaKBoO2kBd6Bs"
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
    local_path = Path(__file__).parent / "공급량(계획_실적).xlsx"
    df = None
    
    try:
        df_sheet = pd.read_csv(sheet_url)
        for col in df_sheet.columns:
            if df_sheet[col].dtype == 'object':
                try:
                    if "일자" not in col and "date" not in col.lower():
                        # [수정된 부분] 데이터의 콤마를 안전하게 제거하도록 보강
                        df_sheet[col] = df_sheet[col].astype(str).str.replace(',', '').astype(float)
                except: pass
        df = df_sheet
    except Exception:
        if local_path.exists():
            try:
                xls = pd.ExcelFile(local_path, engine="openpyxl")
                sheet_name = "일별실적" if "일별실적" in xls.sheet_names else xls.sheet_names[0]
                df = pd.read_excel(xls, sheet_name=sheet_name)
            except: return None
        else: return None

    if df is None: return None

    try:
        df.columns = [str(c).replace(" ", "").strip() for c in df.columns]
        col_date = next((c for c in df.columns if "일자" in c or "date" in c.lower()), None)
        col_mj = next((c for c in df.columns if "실적" in c and ("MJ" in c or "GJ" in c)), None)
        if not col_mj: col_mj = next((c for c in df.columns if "공급량" in c and ("MJ" in c or "GJ" in c)), None)
        col_m3 = next((c for c in df.columns if ("실적" in c or "공급량" in c) and ("M3" in c or "m3" in c)), None)
        
        if not col_date or not col_mj: return None
        
        df[col_date] = pd.to_datetime(df[col_date], errors='coerce')
        df = df.dropna(subset=[col_date])
        
        # [수정된 부분] 콤마가 남아있을 경우를 대비해 다시 한번 안전하게 숫자 변환
        df['val_gj'] = pd.to_numeric(df[col_mj].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        if "MJ" in col_mj.upper(): df['val_gj'] = df['val_gj'] / 1000.0
        
        if col_m3: 
            df['val_m3'] = pd.to_numeric(df[col_m3].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        else: 
            df['val_m3'] = 0
            
        df = df[df['val_gj'] > 0].copy()
        
        if "평균기온(℃)" in df.columns:
             df["평균기온(℃)"] = pd.to_numeric(df["평균기온(℃)"], errors='coerce')
        else:
             df["평균기온(℃)"] = np.nan

        return df[['val_gj', 'val_m3', col_date, '평균기온(℃)']].rename(columns={col_date: '일자'})
    except Exception: return None

# ─────────────────────────────────────────────────────────
# [공통 함수 2] 2026년 계획 데이터 로드
# ─────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _load_2026_plan_excel():
    path = Path(__file__).parent / "2026_연간_일별공급계획_2.xlsx"
    if not path.exists(): return None
    try:
        raw = pd.read_excel(path, sheet_name='연간', header=None)
        header_idx = None
        for i, row in raw.iterrows():
            vals = row.astype(str).values
            if '연' in vals and '월' in vals:
                header_idx = i
                break
        if header_idx is None: return None
        
        df = raw.iloc[header_idx+1:].copy()
        df.columns = raw.iloc[header_idx].astype(str).str.replace(r'\s+', '', regex=True).tolist()
        
        col_map = {}
        for c in df.columns:
            if '연' in c: col_map['y'] = c
            elif '월' in c: col_map['m'] = c
            elif '일' in c: col_map['d'] = c
            elif ('계획' in c or '예상' in c) and 'GJ' in c: col_map['p_gj'] = c
            elif ('계획' in c or '예상' in c) and 'm3' in c: col_map['p_m3'] = c

        df['날짜'] = pd.to_datetime({
            'year': pd.to_numeric(df[col_map['y']], errors='coerce'),
            'month': pd.to_numeric(df[col_map['m']], errors='coerce'),
            'day': pd.to_numeric(df[col_map['d']], errors='coerce')
        }, errors='coerce')
        df = df.dropna(subset=['날짜'])
        
        df['plan_gj'] = pd.to_numeric(df[col_map.get('p_gj')], errors='coerce').fillna(0)
        if col_map.get('p_gj') and "MJ" in col_map['p_gj'].upper():
             df['plan_gj'] = df['plan_gj'] / 1000.0
             
        if col_map.get('p_m3'):
           df['plan_m3'] = pd.to_numeric(df[col_map.get('p_m3')], errors='coerce').fillna(0)
        else:
           df['plan_m3'] = 0
           
        return df[['날짜', 'plan_gj', 'plan_m3']]
    except: return None

# ─────────────────────────────────────────────────────────
# [공통 함수 2-1] 공급량 '계획'을 구글시트에서 로드 (H열: 계획 공급량(MJ), I열: 계획 공급량(M3))
#  - 실적과 같은 시트(gid=0)를 사용. 엑셀 파일은 시트를 읽지 못할 때만 대체용으로 사용
# ─────────────────────────────────────────────────────────
PLAN_SHEET_ID = "13HrIz6OytYDykXeXzXJ02I6XbaKin1YaKBoO2kBd6Bs"


def _parse_plan_sheet(raw: pd.DataFrame) -> Optional[pd.DataFrame]:
    """시트 DataFrame에서 일자·계획(MJ)·계획(M3)을 찾아 (날짜, plan_gj, plan_m3)로 변환"""
    df = raw.copy()
    df.columns = [str(c).replace(" ", "").strip() for c in df.columns]
    col_date = next((c for c in df.columns if "일자" in c or "date" in c.lower()), None)
    col_mj = next((c for c in df.columns if "계획" in c and ("MJ" in c.upper() or "GJ" in c.upper())), None)
    col_m3 = next((c for c in df.columns if "계획" in c and "M3" in c.upper()), None)
    # 헤더 이름으로 못 찾으면 시트의 H열(8번째), I열(9번째)을 사용
    if col_mj is None and len(df.columns) > 7:
        col_mj = df.columns[7]
    if col_m3 is None and len(df.columns) > 8:
        col_m3 = df.columns[8]
    if col_date is None or col_mj is None:
        return None

    def _num(s: pd.Series) -> pd.Series:   # '1,303,693' 같은 콤마 문자열도 숫자로
        return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")

    out = pd.DataFrame({"날짜": pd.to_datetime(df[col_date], errors="coerce")})
    mj = _num(df[col_mj])
    out["plan_gj"] = mj / 1000.0 if "MJ" in col_mj.upper() else mj       # MJ → GJ
    out["plan_m3"] = _num(df[col_m3]) if col_m3 is not None else 0.0
    out = out.dropna(subset=["날짜"])
    out = out[out["plan_gj"].fillna(0) > 0]                              # 계획이 입력된 날만
    out["plan_m3"] = out["plan_m3"].fillna(0)
    out = out.drop_duplicates("날짜", keep="last").sort_values("날짜").reset_index(drop=True)
    return out[["날짜", "plan_gj", "plan_m3"]]


@st.cache_data(show_spinner=False, ttl=600)
def load_2026_plan_with_source():
    """(계획 DataFrame, 출처 문구) 반환. 출처: 구글시트 / 엑셀(대체) / None"""
    url = f"https://docs.google.com/spreadsheets/d/{PLAN_SHEET_ID}/export?format=csv&gid=0"
    try:
        plan = _parse_plan_sheet(pd.read_csv(url))
        if plan is not None and not plan.empty:
            return plan, "구글시트 H·I열"
    except Exception:
        pass
    plan = _load_2026_plan_excel()
    if plan is not None and not plan.empty:
        return plan, "엑셀 파일 (구글시트를 읽지 못해 대체)"
    return None, None


def load_2026_plan_data_common():
    """공급량 계획(날짜, plan_gj, plan_m3). 탭1·탭2 공통 사용"""
    return load_2026_plan_with_source()[0]


def plan_source_caption() -> str:
    _, src = load_2026_plan_with_source()
    return f"계획 출처: {src}" if src else "⚠️ 계획 데이터를 읽지 못했습니다 (구글시트 H·I열 확인)"


# ─────────────────────────────────────────────────────────
# [공통 함수 3] 기온 매트릭스용 구글시트 데이터 로드 (1번째 코드와 동일 소스)
# ─────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=600)
def load_temperature_sheet():
    sheet_id = "13HrIz6OytYDykXeXzXJ02I6XbaKin1YaKBoO2kBd6Bs"
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
    try:
        df = pd.read_csv(url)
        df.columns = [str(c).replace(" ", "").strip() for c in df.columns]
        if "일자" not in df.columns or "평균기온(℃)" not in df.columns:
            return None
        df["일자"] = pd.to_datetime(df["일자"], errors="coerce")
        df["평균기온(℃)"] = pd.to_numeric(
            df["평균기온(℃)"].astype(str).str.replace(",", ""), errors="coerce"
        )
        df = df.dropna(subset=["일자"])
        df["연도"] = df["일자"].dt.year
        df["월"] = df["일자"].dt.month
        df["일"] = df["일자"].dt.day
        # 시트의 '최저' 열(E열)을 최저기온으로 사용
        min_src = next((c for c in df.columns if "최저" in c), None)
        if min_src is not None:
            df["최저기온(℃)"] = pd.to_numeric(
                df[min_src].astype(str).str.replace(",", ""), errors="coerce"
            )
        else:
            df["최저기온(℃)"] = np.nan
        return df[["일자", "연도", "월", "일", "평균기온(℃)", "최저기온(℃)"]]
    except Exception:
        return None


# ─────────────────────────────────────────────────────────
# [공통 설정] 수정 가능한 입력칸(data_editor)의 천단위 콤마 표시
#  - 수정 가능한 열은 표 스타일(Styler) 서식이 적용되지 않아 NumberColumn의 format을 써야 함
#  - "localized"(1,234.5 형식)는 Streamlit 1.45 이상에서 지원, 낮은 버전은 기본 표시로 대체
# ─────────────────────────────────────────────────────────
def _supports_localized_number_format() -> bool:
    try:
        major, minor = (int(x) for x in st.__version__.split(".")[:2])
        return (major, minor) >= (1, 45)
    except Exception:
        return False

NUM_COMMA_FORMAT = "localized" if _supports_localized_number_format() else None


# ─────────────────────────────────────────────────────────
# [공통 함수 4] 시간대별 기온 (기상청 ASOS 시간자료: OBS_ASOS*.csv)
#  - 파일명 뒤의 숫자(다운로드 시각)는 매번 바뀌므로 'OBS_ASOS'로 시작하는 csv를 모두 찾아 사용
#  - 파일이 여러 개면 합쳐서 쓰고, 같은 시각이 겹치면 가장 최근에 받은 파일 값을 사용
#  - 시각 기준: 기상청 관행대로 '24시 = 다음날 00:00' (하루 = 1시 ~ 24시)
# ─────────────────────────────────────────────────────────
def _obs_asos_files() -> List[Path]:
    """app.py와 같은 폴더의 OBS_ASOS*.csv를 오래된 순 → 최신 순으로 반환"""
    base = Path(__file__).parent
    files = [
        p for p in base.iterdir()
        if p.is_file() and p.suffix.lower() == ".csv" and p.name.upper().startswith("OBS_ASOS")
    ]

    def _key(p):
        nums = re.findall(r"\d{8,14}", p.stem)  # 파일명 속 다운로드 시각(예: 20261030083256)
        return (nums[-1].ljust(14, "0") if nums else "", p.stat().st_mtime)

    return sorted(files, key=_key)


def _obs_signature():
    """파일 목록/수정시각이 바뀌면 캐시를 새로 만들기 위한 키"""
    return tuple((p.name, p.stat().st_mtime) for p in _obs_asos_files())


def _read_obs_csv(path: Path) -> Optional[pd.DataFrame]:
    for enc in ("cp949", "utf-8-sig", "euc-kr"):
        try:
            raw = pd.read_csv(path, encoding=enc)
        except Exception:
            continue
        raw.columns = [str(c).strip() for c in raw.columns]
        col_dt = next((c for c in raw.columns if "일시" in c), None)
        col_t = next((c for c in raw.columns
                      if "기온" in c and "QC" not in c.upper() and "플래그" not in c), None)
        if col_dt is None or col_t is None:
            continue  # 인코딩이 안 맞아 열 이름이 깨졌으면 다음 인코딩 시도
        out = pd.DataFrame({
            "dt": pd.to_datetime(raw[col_dt], errors="coerce"),
            "temp": pd.to_numeric(raw[col_t], errors="coerce"),
        })
        col_stn = next((c for c in raw.columns if c == "지점"), None)
        if col_stn is not None and (pd.to_numeric(raw[col_stn], errors="coerce") == 143).any():
            out = out[pd.to_numeric(raw[col_stn], errors="coerce").values == 143]  # 대구만
        return out.dropna(subset=["dt", "temp"])
    return None


@st.cache_data(show_spinner=False, ttl=600)
def load_obs_hourly(signature):
    """OBS_ASOS*.csv 전부를 합쳐 (dt, 일자, 시, temp) 형태로 반환. 없으면 None"""
    frames = [f for f in (_read_obs_csv(p) for p in _obs_asos_files()) if f is not None and not f.empty]
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)           # 오래된 파일 → 최신 파일 순
    df = df.drop_duplicates("dt", keep="last").sort_values("dt")
    df["일자"] = (df["dt"] - pd.Timedelta(minutes=1)).dt.normalize()   # 00:00 → 전날 24시
    df["시"] = df["dt"].dt.hour.replace(0, 24)
    return df[["dt", "일자", "시", "temp"]].reset_index(drop=True)


HOURLY_LOW_TOL = 1.0   # '최저기온 지속' 기준: 그날 최저기온 +1℃ 이내


def hourly_day_stats(day_df: pd.DataFrame, tol: float = HOURLY_LOW_TOL) -> dict:
    """하루(최대 24개 시각) 데이터에서 최저/최고 기온과 발생 시각,
    그리고 '최저기온 지속 구간'(최저 발생 시각을 포함해 최저+tol℃ 이내로 이어진 구간) 계산"""
    d = day_df.sort_values("시")
    h = d["시"].to_numpy()
    t = d["temp"].to_numpy(dtype=float)
    m8 = t[h % 3 == 0]
    i_min = int(t.argmin())
    limit = float(t.min()) + tol + 1e-9
    lo = hi = i_min
    while lo - 1 >= 0 and t[lo - 1] <= limit and h[lo - 1] == h[lo] - 1:
        lo -= 1
    while hi + 1 < len(t) and t[hi + 1] <= limit and h[hi + 1] == h[hi] + 1:
        hi += 1
    return {
        "hours": h, "temps": t,
        "run_start": int(h[lo]), "run_end": int(h[hi]), "run_cnt": int(hi - lo + 1), "tol": tol,
        "tmin": float(t.min()), "tmin_hour": int(h[t.argmin()]),
        "tmax": float(t.max()), "tmax_hour": int(h[t.argmax()]),
        # 구글시트 평균기온이 없을 때만 쓰는 대체값(기상청 방식: 3·6·…·24시 8개 평균)
        "mean_kma": float(m8.mean()) if len(m8) else float(t.mean()),
    }


# 최신일=파랑(굵은 실선+면), D-1=앰버, D-2=회색(얇은 점선), 그 이후는 차분한 보조색
_DAY_COLORS = ["#1A73E8", "#F5A800", "#8F959C", "#34A853", "#A142F4", "#E8710A", "#00ACC1"]
_AXIS_TXT = "#80868B"
_GRID = "rgba(148,163,184,0.20)"


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def build_hourly_compare_figure(days: list) -> go.Figure:
    """days: 최신일 → 과거 순. 하루 1~24시 축에 날짜별 시간대별 기온을 겹쳐 그린다.
    스타일: 최신일은 굵은 파란 곡선 + 아래 옅은 면, 과거일은 얇은 점선."""
    fig = go.Figure()
    all_t = [v for dd in days for v in dd["stats"]["temps"]]
    t_lo = min(all_t + [dd["avg"] for dd in days])
    t_hi = max(all_t + [dd["avg"] for dd in days])
    span = max(t_hi - t_lo, 1.0)
    y_lo, y_hi = t_lo - 0.12 * span, t_hi + 0.24 * span      # 위쪽은 이름표 자리 확보
    label_min = len(days) <= 3          # 날짜가 많으면 글자 겹침을 막기 위해 최저 표시는 마름모만

    # 날짜별 최저기온 지속 구간(최저기온 +1℃ 이내로 이어진 구간)을 그래프 뒤쪽에 음영 + 이름표로 표시
    shade_op = 0.13 if len(days) <= 2 else (0.09 if len(days) <= 4 else 0.06)
    rows_used = []                    # 이름표가 가로로 겹치면 다음 줄로 내려서 배치
    for dd in days:
        r, c = dd["stats"], dd["color"]
        fig.add_vrect(x0=r["run_start"] - 0.5, x1=r["run_end"] + 0.5, fillcolor=c,
                      opacity=shade_op, line_width=0, layer="below")
        left_side = (r["run_start"] + r["run_end"]) / 2 < 12
        x_anchor = (r["run_start"] - 0.5) if left_side else (r["run_end"] + 0.5)
        span_x = (x_anchor, x_anchor + 3.2) if left_side else (x_anchor - 3.2, x_anchor)
        row = 0
        while any(rw == row and not (span_x[1] <= s0 or span_x[0] >= s1) for rw, s0, s1 in rows_used):
            row += 1
        rows_used.append((row, span_x[0], span_x[1]))
        fig.add_annotation(
            x=x_anchor, y=1 - row * 0.1, yref="paper",
            xanchor="left" if left_side else "right", yanchor="top", showarrow=False,
            text=(f"<b>{dd['label']} 최저 {r['tmin']:.1f}℃ 지속<br>"
                  f"{r['run_start']}~{r['run_end']}시 ({r['run_cnt']}시간)</b>"),
            font=dict(color=c, size=12), align="left" if left_side else "right",
        )

    def _line(i, dd, fill):
        s, c = dd["stats"], dd["color"]
        main = (i == 0)
        fig.add_trace(go.Scatter(
            x=s["hours"], y=s["temps"], mode="lines+markers",
            name=f"{dd['label']} {dd['tag']} · 평균 {dd['avg']:.1f}℃", legendrank=i + 1,
            line=dict(color=c, width=3.6 if main else 2.0, dash="solid" if main else "dot",
                      shape="spline", smoothing=1.0),
            marker=dict(size=9 if main else 4, color=c,
                        line=dict(color="white", width=2 if main else 0)),
            fill="tonexty" if fill else None, fillcolor=_rgba(c, 0.10) if fill else None,
            hovertemplate=f"{dd['label']} {dd['tag']} %{{x}}시<br>🌡 %{{y:.1f}}℃<extra></extra>",
        ))

    # 과거일(점선)을 먼저 그리고, 면 채움 기준선 → 최신일(굵은 파랑)을 맨 위에 그린다
    for i in range(len(days) - 1, 0, -1):
        _line(i, days[i], fill=False)
    h0 = days[0]["stats"]["hours"]
    fig.add_trace(go.Scatter(x=h0, y=[y_lo] * len(h0), mode="lines", line=dict(width=0),
                             showlegend=False, hoverinfo="skip"))
    _line(0, days[0], fill=True)

    for dd in days:                    # 그날의 최저기온 마름모
        s, c = dd["stats"], dd["color"]
        fig.add_trace(go.Scatter(
            x=[s["tmin_hour"]], y=[s["tmin"]],
            mode="markers+text" if label_min else "markers",
            text=[f"<b>최저 {s['tmin']:.1f}℃</b>"] if label_min else None,
            textposition="bottom center", textfont=dict(color=c, size=12),
            marker=dict(size=11, symbol="diamond", color=c, line=dict(color="white", width=1.5)),
            showlegend=False, cliponaxis=False,
            hovertemplate=f"{dd['label']} 최저 %{{y:.1f}}℃ (%{{x}}시)<extra></extra>",
        ))

    # 맨 왼쪽(x=0 '평균' 칸)에 날짜별 일평균기온(구글시트): 점선 수평선 + 왼쪽 이름표
    gap = span * 0.06                                  # 평균값이 가까워도 라벨이 겹치지 않도록 최소 간격
    avgs = [dd["avg"] for dd in days]
    order = sorted(range(len(days)), key=lambda k: avgs[k])
    pos = [avgs[k] for k in order]
    for j in range(1, len(pos)):
        pos[j] = max(pos[j], pos[j - 1] + gap)
    drift = (sum(pos) - sum(avgs[k] for k in order)) / len(pos)
    label_y = {k: pos[j] - drift for j, k in enumerate(order)}
    for k, dd in enumerate(days):
        c = dd["color"]
        fig.add_trace(go.Scatter(                      # 평균기온 수평선(점선)
            x=[0, 24.7], y=[dd["avg"], dd["avg"]], mode="lines",
            line=dict(color=c, width=1.4, dash="dash"), opacity=0.6,
            showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=[0], y=[dd["avg"]], mode="markers",
            marker=dict(size=12, symbol="square", color=c, line=dict(color="white", width=1.5)),
            showlegend=False, hovertemplate=f"{dd['label']} 평균 %{{y:.1f}}℃<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=[-0.25], y=[label_y[k]], mode="text", text=[f"<b>{dd['label']} 평균 {dd['avg']:.1f}℃</b>"],
            textposition="middle left", textfont=dict(color=c, size=12),
            showlegend=False, hoverinfo="skip", cliponaxis=False,
        ))
    fig.add_vline(x=0.4, line_dash="dot", line_color="rgba(100,116,139,0.35)", line_width=1)

    fig.update_layout(
        height=520, margin=dict(l=10, r=10, t=50, b=10), plot_bgcolor="white",
        xaxis=dict(title=dict(text="시 (24시 = 다음날 00:00)", font=dict(color=_AXIS_TXT, size=12)),
                   range=[-3.2, 24.7], tickmode="array",
                   tickvals=list(range(0, 25)), ticktext=["평균"] + [str(h) for h in range(1, 25)],
                   showgrid=False, showline=False, zeroline=False, tickfont=dict(color=_AXIS_TXT, size=11)),
        yaxis=dict(title=dict(text="기온 (℃)", font=dict(color=_AXIS_TXT, size=12)), range=[y_lo, y_hi],
                   gridcolor=_GRID, showline=False, zeroline=False, tickfont=dict(color=_AXIS_TXT, size=11)),
        legend=dict(orientation="h", yanchor="bottom", y=1.03, xanchor="right", x=1, font=dict(size=12)),
        hovermode="x unified",
    )
    return fig


def build_hourly_continuous_figure(obs_m: pd.DataFrame, days: list, sheet_avg: dict) -> go.Figure:
    """월초~현재까지 시간별 기온을 가로로 하나의 곡선으로 이어서 표시 (선택한 날짜는 색 음영)"""
    fig = go.Figure()
    for dd in days:
        d0 = pd.Timestamp(dd["date"])
        fig.add_vrect(x0=d0.to_pydatetime(), x1=(d0 + pd.Timedelta(days=1)).to_pydatetime(),
                      fillcolor=dd["color"], opacity=0.10, line_width=0, layer="below")
        fig.add_annotation(
            x=(d0 + pd.Timedelta(hours=12)).to_pydatetime(), y=1, yref="paper", yanchor="bottom",
            showarrow=False, text=f"<b>{dd['label']}</b>", font=dict(color=dd["color"], size=11),
        )
    for dd in days:                 # 날짜별 최저기온 지속 구간은 더 진하게
        r = dd["stats"]
        d_run = pd.Timestamp(dd["date"])
        fig.add_vrect(x0=(d_run + pd.Timedelta(hours=r["run_start"] - 0.5)).to_pydatetime(),
                      x1=(d_run + pd.Timedelta(hours=r["run_end"] + 0.5)).to_pydatetime(),
                      fillcolor=dd["color"], opacity=0.25, line_width=0, layer="below")

    t_lo, t_hi = float(obs_m["temp"].min()), float(obs_m["temp"].max())
    span = max(t_hi - t_lo, 1.0)
    y_lo, y_hi = t_lo - 0.08 * span, t_hi + 0.10 * span
    main_c = _DAY_COLORS[0]
    fig.add_trace(go.Scatter(x=obs_m["dt"], y=[y_lo] * len(obs_m), mode="lines", line=dict(width=0),
                             showlegend=False, hoverinfo="skip"))       # 면 채움 기준선
    fig.add_trace(go.Scatter(
        x=obs_m["dt"], y=obs_m["temp"], mode="lines", name="시간별 기온",
        line=dict(color=main_c, width=2.6, shape="spline", smoothing=0.6),
        fill="tonexty", fillcolor=_rgba(main_c, 0.10),
        hovertemplate="%{x|%m/%d %H:%M}<br>🌡 %{y:.1f}℃<extra></extra>",
    ))
    # 일평균기온(구글시트)을 각 날짜 정오에 앰버 점선으로 표시
    d_first, d_last = obs_m["일자"].min(), obs_m["일자"].max()
    xs, ys = [], []
    for d, v in sorted(sheet_avg.items()):
        if d_first <= d <= d_last:
            xs.append((d + pd.Timedelta(hours=12)).to_pydatetime())
            ys.append(float(v))
    if xs:
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers", name="일평균기온(구글시트)",
            line=dict(color=_DAY_COLORS[1], width=2, dash="dot", shape="spline", smoothing=0.8),
            marker=dict(size=5, color=_DAY_COLORS[1]),
            hovertemplate="%{x|%m/%d} 일평균<br>🌡 %{y:.1f}℃<extra></extra>",
        ))
    fig.update_layout(
        height=520, margin=dict(l=10, r=10, t=50, b=10), plot_bgcolor="white",
        xaxis=dict(title=None, tickformat="%m/%d", dtick=86400000, tickangle=-45,
                   showgrid=False, showline=False, tickfont=dict(color=_AXIS_TXT, size=11),
                   range=[obs_m["dt"].min().to_pydatetime(), obs_m["dt"].max().to_pydatetime()]),
        yaxis=dict(title=dict(text="기온 (℃)", font=dict(color=_AXIS_TXT, size=12)), range=[y_lo, y_hi],
                   gridcolor=_GRID, showline=False, zeroline=False, tickfont=dict(color=_AXIS_TXT, size=11)),
        legend=dict(orientation="h", yanchor="bottom", y=1.03, xanchor="right", x=1, font=dict(size=12)),
        hovermode="x unified",
    )
    return fig


def hourly_temperature_section(key_prefix: str = "hourly_"):
    """[탭2 최하단] '시간대별 기온 분석' 활성화 버튼
    - 기본: 최신일 + D-1 시간대별 기온 겹쳐보기 (그래프 상단 D-n 버튼으로 D-6까지 확장)
    - 우측 '이어보기': 같은 자리에서 당월 1일 ~ 현재까지 가로로 이어진 그래프로 전환"""
    show = st.toggle("🌡️ 시간대별 기온 분석", value=False, key=f"{key_prefix}toggle")
    if not show:
        return

    obs = load_obs_hourly(_obs_signature())
    if obs is None or obs.empty:
        st.info("app.py와 같은 폴더에 `OBS_ASOS`로 시작하는 기상청 시간자료 CSV가 없습니다. "
                "(파일명 뒤 숫자는 달라도 됩니다. 예: OBS_ASOS_TIM_20261030083256.csv)")
        return

    last_day = pd.Timestamp(obs["일자"].max())
    avail = set(pd.to_datetime(obs["일자"].unique()))
    opts = [f"D-{k}" for k in range(1, 7) if (last_day - pd.Timedelta(days=k)) in avail]
    if not opts:
        st.info("비교할 전날(D-1) 자료가 없습니다.")
        return

    # 제목 → 안내 문구 → [D-n 버튼 (좌) | 이어보기 (우)] → 그래프
    st.markdown(f"### 🌡️ 시간대별 기온 분석 · 최신 {last_day:%m/%d}")
    cap_slot = st.empty()          # 안내 문구 자리 (아래 버튼 선택값이 정해진 뒤 채움)

    try:    # 버튼들을 같은 높이로 맞춤 (구버전 streamlit은 옵션이 없어 기본 정렬)
        b_left, b_right = st.columns([4.5, 1.3], vertical_alignment="center")
    except TypeError:
        b_left, b_right = st.columns([4.5, 1.3])
    with b_left:   # 최신일 기준 D-n 버튼 (D-3 = 최신일 + 3일 전까지 = 4일)
        if hasattr(st, "segmented_control"):
            pick = st.segmented_control("비교 기간", opts, default=opts[0], key=f"{key_prefix}dn",
                                        label_visibility="collapsed")
        else:  # 오래된 streamlit 버전 대비
            pick = st.radio("비교 기간", opts, horizontal=True, key=f"{key_prefix}dn",
                            label_visibility="collapsed")
    with b_right:  # 그래프 우측 상단
        cont = st.toggle("이어보기", value=False, key=f"{key_prefix}continue",
                         help=f"{last_day.month}월 1일부터 현재까지 시간별 기온을 가로로 이어서 보여줍니다.")
    pick = pick or opts[0]
    n_back = int(pick.split("-")[1])
    cap_slot.caption(f"비교 기간: 최신일({last_day:%m/%d}) 기준 {pick}까지 총 {n_back + 1}일 · "
                     f"시간자료 최신 관측 {obs['dt'].max():%Y-%m-%d %H:%M}")

    # 평균기온은 구글시트(기상청 일평균) 값을 사용, 시트에 없으면 시간자료로 대체
    ts = load_temperature_sheet()
    sheet_avg = {}
    if ts is not None and not ts.empty:
        sheet_avg = ts.dropna(subset=["평균기온(℃)"]).drop_duplicates("일자", keep="last") \
                      .set_index("일자")["평균기온(℃)"].to_dict()

    days, used_fallback = [], False
    for k in range(0, n_back + 1):
        d_ts = last_day - pd.Timedelta(days=k)
        if d_ts not in avail:
            continue
        stats = hourly_day_stats(obs[obs["일자"] == d_ts])
        if d_ts in sheet_avg:
            avg = float(sheet_avg[d_ts])
        else:
            avg, used_fallback = stats["mean_kma"], True
        days.append({"label": d_ts.strftime("%m/%d"), "tag": "최신" if k == 0 else f"D-{k}",
                     "color": _DAY_COLORS[k], "stats": stats, "avg": avg,
                     "date": d_ts.strftime("%Y-%m-%d"), "n": int(len(stats["hours"]))})

    if cont:
        month_start = last_day.replace(day=1)
        obs_m = obs[obs["dt"] >= month_start].copy()
        st.plotly_chart(build_hourly_continuous_figure(obs_m, days, sheet_avg), use_container_width=True)
        st.caption(f"{obs_m['dt'].min():%m/%d %H:%M} ~ {obs_m['dt'].max():%m/%d %H:%M} · "
                   f"색 음영=선택한 {len(days)}일(진한 부분=날짜별 최저기온 지속 구간) · 주황 점선=일평균기온(구글시트)")
    else:
        st.plotly_chart(build_hourly_compare_figure(days), use_container_width=True)
        runs = " · ".join(f"{dd['label']} {dd['stats']['run_start']}~{dd['stats']['run_end']}시" for dd in days)
        st.caption(f"※ 음영=날짜별 최저기온에서 +{days[0]['stats']['tol']:g}℃ 이내로 이어진 구간 ({runs}) · "
                   "마름모=그날의 최저기온 · 점선·왼쪽 네모=일평균기온(구글시트) · 24시=다음날 00:00")

    st.dataframe(
        pd.DataFrame([{
            "날짜": dd["date"], "구분": dd["tag"],
            "평균기온(℃)": dd["avg"],
            "최저기온(℃)": dd["stats"]["tmin"], "최저 발생(시)": dd["stats"]["tmin_hour"],
            "최고기온(℃)": dd["stats"]["tmax"], "최고 발생(시)": dd["stats"]["tmax_hour"],
            "관측 시간 수": dd["n"],
        } for dd in days]).style.format({"평균기온(℃)": "{:.1f}", "최저기온(℃)": "{:.1f}", "최고기온(℃)": "{:.1f}"})
          .set_properties(**{"text-align": "center"})
          .set_table_styles([dict(selector="th", props=[("text-align", "center")])]),
        use_container_width=True, hide_index=True,
    )

    if len(days) >= 2:
        a, b = days[0], days[1]
        st.info(
            f"{a['label']}(최신) vs {b['label']}({b['tag']}) — "
            f"평균기온 {a['avg']:.1f}℃ vs {b['avg']:.1f}℃ ({a['avg'] - b['avg']:+.1f}℃) · "
            f"최저기온 {a['stats']['tmin']:.1f}℃ vs {b['stats']['tmin']:.1f}℃ "
            f"({a['stats']['tmin'] - b['stats']['tmin']:+.1f}℃)"
        )
    unfinished = [dd for dd in days if dd["n"] < 24]
    if unfinished:
        st.caption("※ " + ", ".join(f"{dd['label']}({dd['n']}시간 관측)" for dd in unfinished)
                   + "는 아직 진행 중이라 최저·최고기온은 현재까지 기준입니다.")
    if used_fallback:
        st.caption("※ 구글시트에 평균기온이 없는 날짜는 시간자료(3·6·…·24시 평균)로 대체했습니다.")


# ==============================================================================
# [탭 1] 도시가스 공급실적 관리
# ==============================================================================
def run_tab1_management():
    if 'tab1_df' not in st.session_state:
        df_hist = load_historical_data_common()
        if df_hist is not None and not df_hist.empty:
            init_df = df_hist.rename(columns={'일자': '날짜', 'val_gj': '실적(GJ)', 'val_m3': '실적(m3)'})
            init_df['계획(GJ)'] = 0.0
            init_df['계획(m3)'] = 0.0
            st.session_state.tab1_df = init_df
        else:
            st.session_state.tab1_df = pd.DataFrame({
                '날짜': [pd.to_datetime('2026-01-01')],
                '계획(GJ)': [0.0], '실적(GJ)': [0.0],
                '계획(m3)': [0.0], '실적(m3)': [0.0],
                '평균기온(℃)': [np.nan]
            })

    df = st.session_state.tab1_df

    df_plan_file = load_2026_plan_data_common()
    if df_plan_file is not None and not df_plan_file.empty:
        plan_gj_map = df_plan_file.set_index('날짜')['plan_gj']
        plan_m3_map = df_plan_file.set_index('날짜')['plan_m3']
        mapped_gj = df['날짜'].map(plan_gj_map)
        df['계획(GJ)'] = np.where(df['계획(GJ)'] == 0, mapped_gj.fillna(0), df['계획(GJ)'])
        mapped_m3 = df['날짜'].map(plan_m3_map)
        df['계획(m3)'] = np.where(df['계획(m3)'] == 0, mapped_m3.fillna(0), df['계획(m3)'])
        st.session_state.tab1_df = df

    st.sidebar.header("📂 [관리] 데이터 파일")
    st.sidebar.caption(plan_source_caption())
    st.sidebar.file_uploader("연간계획 엑셀 업로드", type=['xlsx'], key="u1")
    
    st.title("🔥 도시가스 공급실적 관리")

    col_date, _ = st.columns([1, 4])
    with col_date:
        valid_df = df[df['실적(GJ)'] > 0]
        if not valid_df.empty:
            max_date = valid_df['날짜'].max().date()
        else:
            max_date = pd.to_datetime("today").date()
            
        selected_date = st.date_input("조회 기준일", value=max_date)
        
    target_date = pd.to_datetime(selected_date)

    mask_day = df['날짜'] == target_date
    current_row = df[mask_day]

    api_temp = None
    is_new_data = current_row.empty
    
    if is_new_data or (not current_row.empty and pd.isna(current_row['평균기온(℃)'].iloc[0])):
        api_temp = get_daegu_temperature(target_date.strftime("%Y%m%d"))
        if api_temp is not None:
             st.toast(f"⛅ 기상청 API: {target_date.strftime('%Y-%m-%d')} 대구 기온({api_temp}℃) 수신 성공!")

    if current_row.empty:
        p_gj, p_m3 = 0, 0
        if df_plan_file is not None:
            p_row = df_plan_file[df_plan_file['날짜'] == target_date]
            if not p_row.empty:
                p_gj = p_row['plan_gj'].iloc[0]
                p_m3 = p_row['plan_m3'].iloc[0]

        new_row = pd.DataFrame([{
            '날짜': target_date,
            '계획(GJ)': p_gj, '실적(GJ)': 0,
            '계획(m3)': p_m3, '실적(m3)': 0,
            '평균기온(℃)': api_temp if api_temp is not None else np.nan
        }])
        df = pd.concat([df, new_row], ignore_index=True)
        st.session_state.tab1_df = df
        current_row = df[df['날짜'] == target_date]
    else:
        if api_temp is not None:
            df.loc[mask_day, '평균기온(℃)'] = api_temp
            st.session_state.tab1_df = df
            current_row = df[df['날짜'] == target_date]

    current_val_gj = float(current_row['실적(GJ)'].iloc[0])
    plan_val_gj = float(current_row['계획(GJ)'].iloc[0])
    current_val_m3 = float(current_row['실적(m3)'].iloc[0])
    plan_val_m3 = float(current_row['계획(m3)'].iloc[0])

    rank_text = ""
    is_top_rank = False
    if current_val_gj > 0:
        df_hist = load_historical_data_common()
        if df_hist is not None and not df_hist.empty:
            df_hist = df_hist[df_hist['일자'] != target_date]
            all_vals = pd.concat([df_hist['val_gj'], pd.Series([current_val_gj])])
            rank_all = (all_vals > current_val_gj).sum() + 1
            hist_month = df_hist[df_hist['일자'].dt.month == target_date.month]
            month_vals = pd.concat([hist_month['val_gj'], pd.Series([current_val_gj])])
            rank_month = (month_vals > current_val_gj).sum() + 1
            firecracker = "🎉" if rank_all == 1 else ""
            rank_text = f"{firecracker} 🏆 역대 전체: {int(rank_all)}위  /  📅 역대 {target_date.month}월: {int(rank_month)}위"
            if rank_all == 1: is_top_rank = True

    st.markdown("### 🔥 열량 실적 (GJ)")
    col_g1, col_g2, col_g3 = st.columns(3)
    
    with col_g1:
        diff_gj = current_val_gj - plan_val_gj
        rate_gj = (current_val_gj / plan_val_gj * 100) if plan_val_gj > 0 else 0
        st.metric(label=f"일간 달성률 {rate_gj:.1f}%", value=f"{int(current_val_gj):,} GJ", delta=f"{int(diff_gj):+,} GJ")
        st.caption(f"계획: {int(plan_val_gj):,} GJ")
        if rank_text:
            st.markdown(f"<span style='font-size: 150%; color: red; font-weight: bold;'>{rank_text}</span><br><span style='font-size: 150%; color: black;'>(2014년 1월 1일 이후 랭킹)</span>", unsafe_allow_html=True)
            if is_top_rank:
                st.balloons()
                st.toast("🎉 축하합니다! 역대 최고 공급량(1위)을 달성했습니다! 🎆")

    with col_g2:
        mask_mtd = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month) & (df['날짜'] <= target_date)
        mtd_data = df[mask_mtd]
        a_mtd, p_mtd = mtd_data['실적(GJ)'].sum(), mtd_data['계획(GJ)'].sum()
        rate_mtd = (a_mtd/p_mtd*100) if p_mtd > 0 else 0
        st.metric(label=f"월간 누적 달성률 {rate_mtd:.1f}%", value=f"{int(a_mtd):,} GJ", delta=f"{int(a_mtd-p_mtd):+,} GJ")
        st.caption(f"누적 계획: {int(p_mtd):,} GJ")

    with col_g3:
        mask_ytd = (df['날짜'].dt.year == target_date.year) & (df['날짜'] <= target_date)
        ytd_data = df[mask_ytd]
        a_ytd, p_ytd = ytd_data['실적(GJ)'].sum(), ytd_data['계획(GJ)'].sum()
        rate_ytd = (a_ytd/p_ytd*100) if p_ytd > 0 else 0
        st.metric(label=f"연간 누적 달성률 {rate_ytd:.1f}%", value=f"{int(a_ytd):,} GJ", delta=f"{int(a_ytd-p_ytd):+,} GJ")
        st.caption(f"누적 계획: {int(p_ytd):,} GJ")

    st.markdown("---")
    st.subheader(f"📝 {target_date.month}월 실적 입력")
    st.info("💡 값을 수정하고 엔터(Enter)를 치면 상단 그래프와 랭킹이 즉시 업데이트됩니다.")

    mask_month_view = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month)
    view_df = df.loc[mask_month_view].copy()
    
    # -------------------------------------------------------------------------
    # 1️⃣ 열량(GJ) 입력 (소계 포함, 가운데 정렬 및 천단위 콤마 적용)
    # -------------------------------------------------------------------------
    st.markdown("##### 1️⃣ 열량(GJ) 및 기온 입력")
    
    view_df_gj = view_df[['날짜', '평균기온(℃)', '계획(GJ)', '실적(GJ)']].copy()
    view_df_gj['달성률(%)'] = np.where(view_df_gj['계획(GJ)'] > 0, (view_df_gj['실적(GJ)'] / view_df_gj['계획(GJ)'] * 100), 0.0)
    
    view_df_gj['날짜'] = view_df_gj['날짜'].dt.strftime("%Y-%m-%d")
    
    # 누계 계산
    sum_plan_gj = view_df_gj['계획(GJ)'].sum()
    sum_act_gj = view_df_gj['실적(GJ)'].sum()
    rate_gj_sum = (sum_act_gj / sum_plan_gj * 100) if sum_plan_gj > 0 else 0.0
    avg_temp_gj = view_df_gj['평균기온(℃)'].mean()
    
    # 소계 행 생성
    subtotal_gj = pd.DataFrame([{
        '날짜': '소계',
        '평균기온(℃)': avg_temp_gj,
        '계획(GJ)': sum_plan_gj,
        '실적(GJ)': sum_act_gj,
        '달성률(%)': rate_gj_sum
    }])
    
    disp_gj = pd.concat([view_df_gj, subtotal_gj], ignore_index=True)
    
    # [가운데 정렬 및 천단위 콤마 스타일 적용]
    disp_gj_style = disp_gj.style.format({
        "평균기온(℃)": "{:.1f}",
        "계획(GJ)": "{:,.0f}",
        "실적(GJ)": "{:,.0f}",
        "달성률(%)": "{:.1f}%"
    }).set_properties(**{'text-align': 'center'}).set_table_styles([dict(selector='th', props=[('text-align', 'center')])])
    
    edited_gj = st.data_editor(
        disp_gj_style,
        column_config={
            "날짜": st.column_config.TextColumn("공급일자", disabled=True),
            "평균기온(℃)": st.column_config.NumberColumn("평균기온(℃) ✏️", step=0.1),
            "계획(GJ)": st.column_config.NumberColumn("계획(GJ)", disabled=True),
            "실적(GJ)": st.column_config.NumberColumn("실적(GJ) ✏️", min_value=0, format=NUM_COMMA_FORMAT),
            "달성률(%)": st.column_config.NumberColumn("달성률(%)", disabled=True),
        },
        hide_index=True, use_container_width=True, key="editor_gj"
    )

    # 소계 행 제외하고 원본 업데이트 비교
    edited_gj_data = edited_gj[edited_gj['날짜'] != '소계'].copy()
    
    check_cols = ['계획(GJ)', '실적(GJ)', '평균기온(℃)']
    if not edited_gj_data[check_cols].reset_index(drop=True).equals(view_df[check_cols].reset_index(drop=True)):
        df.loc[mask_month_view, '실적(GJ)'] = edited_gj_data['실적(GJ)'].values
        df.loc[mask_month_view, '평균기온(℃)'] = edited_gj_data['평균기온(℃)'].values
        st.session_state.tab1_df = df
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    
    # -------------------------------------------------------------------------
    # 2️⃣ 부피(천 m³) 입력 (소계 포함, 가운데 정렬 및 천단위 콤마 적용)
    # -------------------------------------------------------------------------
    st.markdown("##### 2️⃣ 부피(천 m³) 및 기온 입력")
    view_m3 = view_df[['날짜', '평균기온(℃)', '계획(m3)', '실적(m3)']].copy()
    view_m3['계획(천m3)'] = view_m3['계획(m3)'].apply(lambda x: int(x/1000) if x > 10000 else int(x))
    view_m3['실적(천m3)'] = view_m3['실적(m3)'].apply(lambda x: int(x/1000) if x > 10000 else int(x))
    view_m3['달성률(%)'] = np.where(view_m3['계획(천m3)'] > 0, (view_m3['실적(천m3)'] / view_m3['계획(천m3)'] * 100), 0.0)

    view_m3_disp = view_m3[['날짜', '평균기온(℃)', '계획(천m3)', '실적(천m3)', '달성률(%)']].copy()
    view_m3_disp['날짜'] = view_m3_disp['날짜'].dt.strftime("%Y-%m-%d")

    # 누계 계산
    sum_plan_m3 = view_m3_disp['계획(천m3)'].sum()
    sum_act_m3 = view_m3_disp['실적(천m3)'].sum()
    rate_m3_sum = (sum_act_m3 / sum_plan_m3 * 100) if sum_plan_m3 > 0 else 0.0
    avg_temp_m3 = view_m3_disp['평균기온(℃)'].mean()

    # 소계 행 생성
    subtotal_m3 = pd.DataFrame([{
        '날짜': '소계',
        '평균기온(℃)': avg_temp_m3,
        '계획(천m3)': sum_plan_m3,
        '실적(천m3)': sum_act_m3,
        '달성률(%)': rate_m3_sum
    }])
    
    disp_m3 = pd.concat([view_m3_disp, subtotal_m3], ignore_index=True)

    # [가운데 정렬 및 천단위 콤마 스타일 적용]
    disp_m3_style = disp_m3.style.format({
        "평균기온(℃)": "{:.1f}",
        "계획(천m3)": "{:,.0f}",
        "실적(천m3)": "{:,.0f}",
        "달성률(%)": "{:.1f}%"
    }).set_properties(**{'text-align': 'center'}).set_table_styles([dict(selector='th', props=[('text-align', 'center')])])

    edited_m3 = st.data_editor(
        disp_m3_style,
        column_config={
            "날짜": st.column_config.TextColumn("공급일자", disabled=True),
            "평균기온(℃)": st.column_config.NumberColumn("평균기온(℃) ✏️", step=0.1),
            "계획(천m3)": st.column_config.NumberColumn("계획(천m³)", disabled=True),
            "실적(천m3)": st.column_config.NumberColumn("실적(천m³) ✏️", min_value=0, format=NUM_COMMA_FORMAT),
            "달성률(%)": st.column_config.NumberColumn("달성률(%)", disabled=True),
        },
        hide_index=True, use_container_width=True, key="editor_m3"
    )

    # 소계 행 제외하고 원본 업데이트 비교
    edited_m3_data = edited_m3[edited_m3['날짜'] != '소계'].copy()

    check_cols_m3 = ['계획(천m3)', '실적(천m3)', '평균기온(℃)']
    if not edited_m3_data[check_cols_m3].reset_index(drop=True).equals(view_m3[check_cols_m3].reset_index(drop=True)):
        new_plan_m3 = edited_m3_data['계획(천m3)'] * 1000
        new_act_m3 = edited_m3_data['실적(천m3)'] * 1000
        df.loc[mask_month_view, '계획(m3)'] = new_plan_m3.values
        df.loc[mask_month_view, '실적(m3)'] = new_act_m3.values
        df.loc[mask_month_view, '평균기온(℃)'] = edited_m3_data['평균기온(℃)'].values
        st.session_state.tab1_df = df
        st.rerun()

    st.markdown("---")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='연간', index=False)
    st.download_button("💾 관리 데이터 엑셀 저장", buffer, f"실적데이터_{target_date.strftime('%Y%m%d')}.xlsx")

# ==============================================================================
# [탭 2] 공급량 분석
# ==============================================================================
def run_tab2_analysis():
    def center_style(styler):
        styler = styler.set_properties(**{"text-align": "center"})
        styler = styler.set_table_styles([dict(selector="th", props=[("text-align", "center")])])
        return styler

    def pick_default_year_2026(years: List[int]) -> int:
        if 2026 in years: return 2026
        return years[-1]

    def load_supply_sheets(excel_bytes):
        xls = pd.ExcelFile(io.BytesIO(excel_bytes), engine="openpyxl")
        return (xls.parse("월별계획_실적") if "월별계획_실적" in xls.sheet_names else pd.DataFrame(),
                xls.parse("일별실적") if "일별실적" in xls.sheet_names else pd.DataFrame())
    
    def load_2026_plan_file():
        plan = load_2026_plan_data_common()
        if plan is None or plan.empty: return None
        return plan[['날짜', 'plan_gj']].dropna()

    def clean_supply_month_df(df):
        if df.empty: return df
        df = df.copy()
        if "Unnamed: 0" in df.columns: df = df.drop(columns=["Unnamed: 0"])
        df["연"] = pd.to_numeric(df["연"], errors="coerce").astype("Int64")
        df["월"] = pd.to_numeric(df["월"], errors="coerce").astype("Int64")
        num_cols = [c for c in df.columns if c not in ["연", "월"]]
        for c in num_cols: df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        df = df.dropna(subset=["연", "월"])
        df["연"] = df["연"].astype(int)
        df["월"] = df["월"].astype(int)
        return df

    def clean_supply_day_df(df):
        if df.empty: return df
        df = df.copy()
        df["일자"] = pd.to_datetime(df["일자"], errors="coerce")
        for c in ["공급량(MJ)", "공급량(M3)", "공급량(m3)", "평균기온(℃)"]:
            if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        df = df.dropna(subset=["일자"])
        return df

    def render_section_selector_daily(long_df, title, key_prefix):
        st.markdown(f"#### ✅ {title} 기준 선택")
        if long_df.empty:
            st.info("데이터가 없습니다.")
            return 0, 1, []
        years_all = sorted(long_df["연"].unique().tolist())
        default_year = pick_default_year_2026(years_all)
        c1, c2, c3 = st.columns([1.2, 1.2, 1.6])
        with c1: sel_year = st.selectbox("기준 연도", years_all, index=years_all.index(default_year), key=f"{key_prefix}year")
        with c2: sel_month = st.selectbox("기준 월", list(range(1, 13)), index=datetime.now(timezone(timedelta(hours=9))).month - 1, key=f"{key_prefix}month")  # 기본값: 현재 월(한국시간) 
        with c3: st.markdown(f"<div style='padding-top:28px;font-size:14px;color:#666;'>집계 기준: <b>당월(일별)</b></div>", unsafe_allow_html=True)
        st.markdown(f"<div style='margin-top:-4px;font-size:13px;color:#666;'>선택 기준: <b>{sel_year}년 {sel_month}월</b></div>", unsafe_allow_html=True)
        return sel_year, sel_month, years_all

    def _render_supply_top_card(rank, row, icon, gradient):
        date_str = f"{int(row['연'])}년 {int(row['월'])}월 {int(row['일'])}일"
        supply_str = f"{row['공급량_GJ']:,.1f} GJ"
        
        col_m3 = "공급량(M3)" if "공급량(M3)" in row.index else "공급량(m3)"
        m3_val = row.get(col_m3, 0)
        m3_str = f"{m3_val/1000:,.1f} 천m³"
        
        temp_str = f"{row['평균기온(℃)']:.1f}℃" if not pd.isna(row["평균기온(℃)"]) else "-"
        
        html = f"""<div style="border-radius:20px;padding:16px 20px;background:{gradient};box-shadow:0 4px 14px rgba(0,0,0,0.06);margin-top:8px;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;"><div style="font-size:32px;">{icon}</div><div style="font-size:19px;font-weight:700;">최대 공급량 기록 {rank}위</div></div>
        <div style="font-size:18px;margin-bottom:4px;">📅 <b>{date_str}</b></div>
        <div style="font-size:18px;margin-bottom:4px;">🔥 공급량: <b>{supply_str}</b></div>
        <div style="font-size:16px;margin-bottom:4px;color:#555;">📦 부피: <b>{m3_str}</b></div>
        <div style="font-size:18px;margin-bottom:8px;">🌡 평균기온: <b>{temp_str}</b></div>
        </div>"""
        st.markdown(html, unsafe_allow_html=True)

    def temperature_matrix(day_df, default_month, key_prefix):
        st.markdown("### 🌡️ 기온 매트릭스 (일별 평균기온)")

        # 1) 구글 스프레드시트 우선 사용 (1번째 코드와 동일 데이터)
        temp_df = load_temperature_sheet()

        # 2) 실패 시 엑셀 일별실적으로 대체 (0으로 채워진 값은 결측 처리)
        if temp_df is None or temp_df.empty:
            if day_df.empty or "평균기온(℃)" not in day_df.columns:
                st.info("기온 데이터가 없습니다.")
                return
            temp_df = day_df[["일자", "평균기온(℃)"]].copy()
            temp_df["평균기온(℃)"] = temp_df["평균기온(℃)"].replace(0, np.nan)
            temp_df["연도"] = temp_df["일자"].dt.year
            temp_df["월"] = temp_df["일자"].dt.month
            temp_df["일"] = temp_df["일자"].dt.day

        min_y = int(temp_df["연도"].min())
        max_y = int(temp_df["연도"].max())

        c1, c2 = st.columns([2, 1.2])
        with c1:
            yr_range = st.slider(
                "기온 매트릭스 연도 범위 설정",
                min_value=min_y, max_value=max_y,
                value=(min_y, max_y), step=1,
                key=f"{key_prefix}yr_range"
            )
        with c2:
            sel_m = st.selectbox(
                "월 선택", options=list(range(1, 13)),
                index=default_month - 1,
                format_func=lambda x: f"{x}월",
                key=f"{key_prefix}month"
            )

        filtered_df = temp_df[
            (temp_df["월"] == sel_m) &
            (temp_df["연도"] >= yr_range[0]) &
            (temp_df["연도"] <= yr_range[1])
        ]
        if filtered_df.empty:
            st.info("선택한 조건의 데이터가 없습니다.")
            return

        pivot_df = filtered_df.pivot_table(
            index="일", columns="연도", values="평균기온(℃)", aggfunc="mean"
        )
        pivot_df = pivot_df.reindex(list(range(1, 32)))

        avg_series = filtered_df.groupby("연도")["평균기온(℃)"].mean()
        pivot_df.loc["평균"] = avg_series

        pivot_df.index = pivot_df.index.astype(str)
        pivot_df.columns = pivot_df.columns.astype(str)

        fig_heatmap = px.imshow(
            pivot_df,
            labels=dict(x="연도", y="일", color="평균기온(℃)"),
            x=pivot_df.columns,
            y=pivot_df.index,
            color_continuous_scale="RdBu_r",
            aspect="auto",
            text_auto=".1f"
        )

        fig_heatmap.update_layout(
            height=1000,
            margin=dict(l=40, r=40, t=80, b=40),
            yaxis=dict(type="category", tickmode="linear", dtick=1, autorange="reversed"),
            xaxis=dict(type="category", tickmode="linear", dtick=1, side="top")
        )
        fig_heatmap.update_traces(
            textfont=dict(size=14),
            hovertemplate="<b>%{x}년 " + str(sel_m) + "월 %{y}일</b><br>🌡️ 평균기온: %{z:.1f}℃<extra></extra>"
        )

        st.plotly_chart(fig_heatmap, use_container_width=True)
        st.caption(f"{sel_m}월 기준 · 선택연도 {yr_range[0]}~{yr_range[1]}")

    def temperature_supply_band_section(day_df, default_month, key_prefix):
        st.markdown("### 🔥 기온 구간별 평균 공급량 분석")
        act_col = "공급량(MJ)"
        if day_df.empty or "평균기온(℃)" not in day_df.columns or act_col not in day_df.columns: return
        df = day_df.copy()
        df["연"] = df["일자"].dt.year
        df["월"] = df["일자"].dt.month
        years = sorted(df["연"].unique().tolist())
        if not years: return
        min_y, max_y = years[0], years[-1]
        c1, c2 = st.columns([2, 1.2])
        with c1: yr_range = st.slider("연도 범위(공급량 분석)", min_value=min_y, max_value=max_y, value=(max(min_y, max_y - 4), max_y), step=1, key=f"{key_prefix}yr_range")
        with c2: sel_m = st.selectbox("월 선택(공급량 분석)", options=list(range(1, 13)), index=default_month - 1, key=f"{key_prefix}month")
        
        sub = df[(df["연"].between(yr_range[0], yr_range[1])) & (df["월"] == sel_m)].copy()
        sub = sub.dropna(subset=["평균기온(℃)", act_col])
        if sub.empty: return
        
        bins = [-100, -10, -5, 0, 5, 10, 15, 20, 25, 30, 100]
        labels = ["<-10℃", "-10~-5℃", "-5~0℃", "0~5℃", "5~10℃", "10~15℃", "15~20℃", "20~25℃", "25~30℃", "≥30℃"]
        
        sub["기온구간"] = pd.cut(sub["평균기온(℃)"], bins=bins, labels=labels, right=False).astype(str)
        
        grp = sub.groupby("기온구간", as_index=False).agg(
            평균공급량_GJ=(act_col, lambda x: x.mean() / 1000.0), 
            일수=(act_col, "count")
        )
        
        full_bands = pd.DataFrame({"기온구간": labels})
        grp = pd.merge(full_bands, grp, on="기온구간", how="left")
        grp["평균공급량_GJ"] = grp["평균공급량_GJ"].fillna(0)
        grp["일수"] = grp["일수"].fillna(0)
        
        grp["sort_idx"] = grp["기온구간"].map({label: i for i, label in enumerate(labels)})
        grp = grp.sort_values("sort_idx").drop(columns=["sort_idx"])
        
        fig = px.bar(grp, x="기온구간", y="평균공급량_GJ", text="일수",
                      category_orders={"기온구간": labels}) 
                      
        fig.update_layout(
            xaxis_title="기온 구간", 
            yaxis_title="평균 공급량 (GJ)", 
            margin=dict(l=10, r=10, t=40, b=10)
        )
        fig.update_xaxes(type='category', categoryorder='array', categoryarray=labels)
        fig.update_traces(texttemplate="%{text}일", textposition="outside")
        st.plotly_chart(fig, use_container_width=True)
        
        display_tbl = grp.rename(columns={"평균공급량_GJ": "평균공급량(GJ)"})
        st.dataframe(center_style(display_tbl.style.format({"평균공급량(GJ)": "{:,.1f}"})), use_container_width=True, hide_index=True)

    def supply_daily_main_logic(day_df, month_df, sel_year, sel_month, key_prefix):
        st.markdown("## 📅 공급량 분석(일)")
        if day_df.empty or month_df.empty: return
        act_col = "공급량(MJ)"
        if act_col not in day_df.columns: return
        # 구글시트에 최근 입력된 실적(공급량·기온)을 엑셀 마지막 실적일 이후 날짜만 보충
        sheet_df = load_historical_data_common()
        if sheet_df is not None and not sheet_df.empty:
            last_xl = day_df.loc[day_df[act_col] > 0, "일자"].max()
            sd = sheet_df.copy() if pd.isna(last_xl) else sheet_df[sheet_df["일자"] > last_xl].copy()
            if not sd.empty:
                sd[act_col] = sd["val_gj"] * 1000
                sd = sd.rename(columns={"val_m3": "공급량(M3)"})
                sd = sd[["일자", act_col, "공급량(M3)", "평균기온(℃)"]]
                day_df = pd.concat([day_df, sd]).drop_duplicates(subset=["일자"], keep="last").sort_values("일자")

        if 'tab1_df' in st.session_state and st.session_state.tab1_df is not None:
            new_data = st.session_state.tab1_df.copy()
            new_data = new_data[new_data['실적(GJ)'] > 0].copy()
            new_data = new_data[['날짜', '실적(GJ)', '실적(m3)', '평균기온(℃)']] # m3 포함 로드
            new_data.columns = ['일자', act_col, '공급량(M3)', '평균기온(℃)'] # 컬럼 매핑
            new_data[act_col] = new_data[act_col] * 1000 
            day_df = pd.concat([day_df, new_data]).drop_duplicates(subset=['일자'], keep='last').sort_values('일자')
        df_all = day_df.copy()
        df_all["연"] = df_all["일자"].dt.year
        df_all["월"] = df_all["일자"].dt.month
        df_all["일"] = df_all["일자"].dt.day
        this_df = df_all[(df_all["연"] == sel_year) & (df_all["월"] == sel_month)].copy()

        last_valid_date = df_all[df_all[act_col] > 0]['일자'].max()
        if pd.notna(last_valid_date):
            this_df = this_df[this_df['일자'] <= last_valid_date]

        plan_df = load_2026_plan_file()
        plan_curve_x = []
        plan_curve_y = []
        if plan_df is not None:
            plan_month = plan_df[(plan_df['날짜'].dt.year == sel_year) & (plan_df['날짜'].dt.month == sel_month)]
            if not plan_month.empty:
                plan_curve_x = plan_month['날짜'].dt.day.tolist()
                plan_curve_y = plan_month['plan_gj'].tolist()
        st.markdown(f"### 📈 {sel_month}월 일별 패턴 비교")
        cand_years = sorted(df_all["연"].unique().tolist())
        past_candidates = [y for y in cand_years if y < sel_year]
        default_years = past_candidates[-5:]  # 기본: 최근 5개 과거 연도
        past_years = st.multiselect("과거 연도 선택", options=past_candidates, default=default_years, key=f"{key_prefix}past_years")
        fig1 = go.Figure()
        if plan_curve_x:
            fig1.add_scatter(x=plan_curve_x, y=plan_curve_y, mode="lines", name=f"{sel_year}년 {sel_month}월 계획 (사업계획)", line=dict(color="#FF4B4B", width=3, dash="dot"), hovertemplate="%{y:,.0f} GJ<extra></extra>")
        pastel_colors = ["#93C5FD", "#A5B4FC", "#C4B5FD", "#FDA4AF", "#FCA5A5", "#FCD34D", "#86EFAC"]
        prev_year = sel_year - 1
        for idx, y in enumerate(past_years):
            sub = df_all[(df_all["연"] == y) & (df_all["월"] == sel_month)].copy()
            if sub.empty: continue
            line_color = "#3B82F6" if y == prev_year else pastel_colors[idx % len(pastel_colors)]
            line_width = 3 if y == prev_year else 1.5
            op_mode = "lines+markers" if y == prev_year else "lines"
            fig1.add_scatter(x=sub["일"], y=sub[act_col] / 1000.0, mode=op_mode, name=f"{y}년 {sel_month}월 실적", line=dict(color=line_color, width=line_width), hovertemplate="%{y:,.0f} GJ<extra></extra>")
        if not this_df.empty: 
            fig1.add_scatter(x=this_df["일"], y=this_df[act_col] / 1000.0, mode="lines+markers", name=f"{sel_year}년 {sel_month}월 실적", line=dict(color="black", width=4), hovertemplate="%{y:,.0f} GJ<extra></extra>")
        fig1.update_layout(title=f"{sel_year}년 {sel_month}월 일별 공급량 패턴", xaxis_title="일", yaxis_title="공급량 (GJ)", margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig1, use_container_width=True)

        # ─────────────────────────────────────────────
        # 📊 [NEW] 연도별 월 누적 공급량 · 평균기온 비교
        # ─────────────────────────────────────────────
        cmp_years = sorted(set(past_years + [sel_year]))
        cutoff_day = int(this_df["일"].max()) if not this_df.empty else 31

        # 제목(좌) + 옵션 토글(우측 상단)
        hd_title, hd_opt1, hd_opt2, hd_opt3 = st.columns([3, 1.5, 0.9, 1.3])
        with hd_title:
            st.markdown(f"### 📊 {sel_month}월 연도별 누적 공급량 · 평균기온 비교")
        with hd_opt1:
            use_cutoff = st.toggle(
                f"현재 누적일수 비교 (1~{cutoff_day}일)", value=False,
                key=f"{key_prefix}cum_cutoff"
            )
        with hd_opt2:
            show_min = st.toggle("최저기온", value=False, key=f"{key_prefix}cum_min")
        with hd_opt3:
            show_hh = st.toggle("가정용 청구전수", value=False, key=f"{key_prefix}cum_hh")

        period_txt = f"1~{cutoff_day}일" if use_cutoff else "월말까지(월 전체)"
        st.caption(f"집계 기간: {sel_month}월 {period_txt}")

        # 최저기온: 구글시트 '최저' 열 우선, 시트에 값이 없는 날짜는 기상청 API(대구 143)로 보충
        def min_temp_by_day(y, month, days):
            idx = sorted({int(d) for d in days})
            result = pd.Series(np.nan, index=idx, dtype=float)
            ts = load_temperature_sheet()
            if ts is not None and "최저기온(℃)" in ts.columns:
                s = (ts[(ts["연도"] == y) & (ts["월"] == month)]
                     .drop_duplicates("일", keep="last")
                     .set_index("일")["최저기온(℃)"])
                result = s.reindex(idx)
            if result.isna().any():
                mt = get_daegu_month_temps(int(y), int(month))
                if mt is not None and not mt.empty:
                    m = mt.drop_duplicates("일", keep="last").set_index("일")["최저기온"].reindex(idx)
                    result = result.fillna(m)
            return result

        hh_fallback = {}  # 선택 월 자료가 없어 최근 월 값으로 대체한 연도 {"2026년": 9}
        cum_rows = []
        for y in cmp_years:
            sub = df_all[(df_all["연"] == y) & (df_all["월"] == sel_month)].copy()
            if use_cutoff:
                sub = sub[sub["일"] <= cutoff_day]
            sub = sub[sub[act_col] > 0]
            if sub.empty:
                continue
            temp_s = sub["평균기온(℃)"].replace(0, np.nan)  # 0으로 채워진 결측 제외
            row = {
                "연도": f"{y}년",
                "누적공급량(GJ)": sub[act_col].sum() / 1000.0,
                "평균기온(℃)": temp_s.mean(),
            }
            if show_min:
                # 집계 기간 중 가장 낮았던 일 최저기온
                row["최저기온(℃)"] = min_temp_by_day(y, sel_month, sub["일"].tolist()).min()
            if show_hh:
                hh_val, hh_used = household_total(y, sel_month)
                row["가정용 청구전수"] = hh_val
                if hh_used is not None and hh_used != (int(y), int(sel_month)):
                    hh_fallback[f"{y}년"] = hh_used[1]
            row["일수"] = len(sub)
            cum_rows.append(row)

        if cum_rows:
            cum_df = pd.DataFrame(cum_rows)

            if show_min and cum_df["최저기온(℃)"].isna().all():
                st.warning("최저기온 데이터를 가져오지 못했습니다. (구글시트 '최저' 열과 기상청 API 모두 값이 없음)")

            # 팔레트: 과거=라이트 그레이(#BEBEBE), 기준연도=블루(#005AC8), 평균기온=앰버, 최저기온=틸, 가정용 청구전수=스카이 블루
            C_PAST, C_SEL, C_AVG, C_MIN, C_TXT = "#BEBEBE", "#005AC8", "#F08C00", "#0F9D7A", "#475569"
            C_AVG_TXT, C_MIN_TXT = "#B45309", "#047857"          # 기온 라벨 글자색(회색 막대 위)
            C_AVG_TXT_SEL, C_MIN_TXT_SEL = "#FDE68A", "#6EE7B7"  # 기준연도(진한 파랑 막대) 위에서는 밝은 글자색
            C_HH, C_HH_TXT = "#0EA5E9", "#0369A1"
            sel_label = f"{sel_year}년"
            bar_colors = [C_SEL if c == sel_label else C_PAST for c in cum_df["연도"]]

            # ── 세로 배치(보조축 범위 조정) ──
            # 기온선은 '가장 짧은 막대의 상단보다 아래'(막대 몸통 안쪽)에 두어 막대 상단 숫자와 겹치지 않게 하고,
            # 평균기온/최저기온은 각각 따로 눈금을 잡아 위아래 폭이 크게 보이도록 함
            # 가정용 청구전수를 켜면 막대 위쪽에 선이 들어갈 여백을 더 확보
            y1_max = float(cum_df["누적공급량(GJ)"].max()) * (1.3 if show_hh else 1.15)

            def band_range(vals, lo_frac, hi_frac, min_span):
                """vals가 축 높이의 lo_frac~hi_frac 구간에 놓이도록 하는 축 범위를 반환"""
                v_min, v_max = float(vals.min()), float(vals.max())
                if v_max - v_min < min_span:  # 거의 평평하면 최소 폭 확보
                    mid = (v_max + v_min) / 2
                    v_min, v_max = mid - min_span / 2, mid + min_span / 2
                span = (v_max - v_min) / (hi_frac - lo_frac)
                lo = v_min - lo_frac * span
                return [lo, lo + span]

            def label_positions(vals):
                """꺾은선 라벨이 자기 선과 겹치지 않도록 점마다 위치 선택:
                봉우리=위, 골짜기=아래, 오르막=왼쪽 위, 내리막=오른쪽 위"""
                v = list(vals)
                pos = []
                for i, cur in enumerate(v):
                    if pd.isna(cur):
                        pos.append("top center")
                        continue
                    prev_v = v[i - 1] if i > 0 and pd.notna(v[i - 1]) else cur
                    next_v = v[i + 1] if i < len(v) - 1 and pd.notna(v[i + 1]) else cur
                    if cur >= prev_v and cur >= next_v:
                        pos.append("top center")
                    elif cur <= prev_v and cur <= next_v:
                        pos.append("bottom center")
                    elif prev_v < cur:
                        pos.append("top left")
                    else:
                        pos.append("top right")
                return pos

            # 기온선 위치: 평균기온선의 중심을 '전체 막대 높이의 중앙'(막대 높이 평균의 절반)에 맞추고,
            # 오르내림 폭은 좁게 잡아 모든 연도의 점이 막대 중간대에 들어오게 함. 최저기온선은 그 아래에 배치.
            bar_fracs = cum_df["누적공급량(GJ)"] / y1_max
            bar_top_min = float(bar_fracs.min())
            avg_half = 0.06 if show_min else 0.08          # 평균기온선 위아래 반폭(축 높이 대비)
            mid_floor = 0.26 if show_min else 0.16
            mid = max(mid_floor, min(0.5 * float(bar_fracs.mean()), bar_top_min - 0.07 - avg_half))
            avg_band = (mid - avg_half, mid + avg_half)
            if show_min:
                min_band = (0.05, avg_band[0] - 0.085)  # 평균기온선 아래, 라벨이 겹치지 않도록 간격 확보
            else:
                min_band = None

            avg_vals = cum_df["평균기온(℃)"].dropna()
            avg_range = band_range(avg_vals, avg_band[0], avg_band[1], 2.0) if not avg_vals.empty else None
            min_range = None
            if show_min:
                min_vals = cum_df["최저기온(℃)"].dropna()
                if not min_vals.empty:
                    min_range = band_range(min_vals, min_band[0], min_band[1], 2.0)

            # 가정용 청구전수는 막대 위쪽 여백 영역에 별도(숨김) 축으로 배치
            hh_range = None
            if show_hh:
                hh_vals = cum_df["가정용 청구전수"].dropna()
                if hh_vals.empty:
                    st.info(f"{sel_month}월 가정용 청구전수 데이터가 없습니다. (코드 상단 HOUSEHOLD_MONTHLY에 (연, 월): 값을 추가하세요)")
                else:
                    bar_top_max = float(cum_df["누적공급량(GJ)"].max()) / y1_max
                    hh_lo = bar_top_max + 0.08
                    hh_hi = min(0.94, hh_lo + 0.0455)  # 상승 폭(기존 0.065)을 30% 줄여 더 완만한 기울기로 표현
                    hh_range = band_range(hh_vals, hh_lo, hh_hi, 1.0)

            # 그래프는 폭을 넓히고(약 70%), 표는 그래프 바로 아래에 배치
            chart_col, _ = st.columns([7, 3])

            with chart_col:
                fig_cum = make_subplots(specs=[[{"secondary_y": True}]])
                fig_cum.add_trace(
                    go.Bar(
                        x=cum_df["연도"], y=cum_df["누적공급량(GJ)"],
                        name="누적 공급량(GJ)", marker_color=bar_colors,
                        text=cum_df["누적공급량(GJ)"].map(lambda v: f"{v:,.0f}"),
                        textposition="outside",
                        textfont=dict(color=C_TXT, size=12),
                        hovertemplate="%{x}<br>누적: %{y:,.0f} GJ<extra></extra>",
                    ),
                    secondary_y=False,
                )

                def add_temp_line(col, name, color, txt_color, txt_color_sel, dash, symbol, axis):
                    # 흰색 바탕선(케이싱)을 먼저 깔아 막대 위에서도 선이 또렷하게 보이도록 함
                    fig_cum.add_trace(
                        go.Scatter(
                            x=cum_df["연도"], y=cum_df[col], mode="lines", yaxis=axis,
                            line=dict(color="rgba(255,255,255,0.9)", width=6),
                            hoverinfo="skip", showlegend=False,
                        )
                    )
                    # 기준연도(진한 파랑 막대) 위의 라벨만 밝은 글자색으로 표시
                    label_colors = [txt_color_sel if c == sel_label else txt_color for c in cum_df["연도"]]
                    fig_cum.add_trace(
                        go.Scatter(
                            x=cum_df["연도"], y=cum_df[col], name=f"{name}(℃)",
                            mode="lines+markers+text", yaxis=axis,
                            line=dict(color=color, width=2.5, dash=dash),
                            marker=dict(size=9, symbol=symbol, color=color, line=dict(color="white", width=2)),
                            text=cum_df[col].map(lambda v: f"<b>{v:.1f}℃</b>" if pd.notna(v) else ""),
                            textposition=label_positions(cum_df[col]),
                            textfont=dict(color=label_colors, size=12),
                            hovertemplate="%{x}<br>" + name + ": %{y:.1f}℃<extra></extra>",
                        )
                    )

                # 평균기온=보조축(y2), 최저기온=별도 축(y4), 가정용 청구전수=별도 축(y3) — 모두 눈금은 숨김
                add_temp_line("평균기온(℃)", "평균기온", C_AVG, C_AVG_TXT, C_AVG_TXT_SEL, "solid", "circle", "y2")
                if show_min and min_range is not None:
                    add_temp_line("최저기온(℃)", "최저기온", C_MIN, C_MIN_TXT, C_MIN_TXT_SEL, "dot", "diamond", "y4")
                if show_hh and hh_range is not None:
                    fig_cum.add_trace(
                        go.Scatter(
                            x=cum_df["연도"], y=cum_df["가정용 청구전수"], name="가정용 청구전수",
                            mode="lines+markers+text", yaxis="y3",
                            line=dict(color=C_HH, width=2.5, dash="dash"),
                            marker=dict(size=8, symbol="square", color=C_HH, line=dict(color="white", width=2)),
                            text=[
                                (f"<b>{v:,.0f}{'*' if yr in hh_fallback else ''}</b>" if pd.notna(v) else "")
                                for yr, v in zip(cum_df["연도"], cum_df["가정용 청구전수"])
                            ],
                            textposition="top center",
                            textfont=dict(color=C_HH_TXT, size=11),
                            cliponaxis=False,
                            hovertemplate="%{x}<br>가정용 청구전수: %{y:,.0f}<extra></extra>",
                        )
                    )

                # 제목은 넣지 않고(위 소제목/캡션으로 대체), 범례는 아래로 이동해 겹침 방지
                fig_cum.update_layout(
                    height=560,
                    margin=dict(l=10, r=10, t=20, b=70),
                    legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5),
                    bargap=0.4,
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(size=12, color=C_TXT),
                )
                fig_cum.update_xaxes(showgrid=False, linecolor="rgba(148,163,184,0.5)")
                fig_cum.update_yaxes(
                    title_text="누적 공급량 (GJ)", secondary_y=False,
                    range=[0, y1_max],
                    gridcolor="rgba(148,163,184,0.25)", zeroline=False
                )
                # 기온 값은 각 점의 라벨로 표시하므로 보조축 눈금은 숨김
                fig_cum.update_yaxes(
                    secondary_y=True, visible=False, showgrid=False,
                    zeroline=False, range=avg_range
                )
                if show_min and min_range is not None:
                    fig_cum.update_layout(yaxis4=dict(
                        overlaying="y", side="right", visible=False,
                        showgrid=False, zeroline=False, range=min_range
                    ))
                if show_hh and hh_range is not None:
                    fig_cum.update_layout(yaxis3=dict(
                        overlaying="y", side="right", visible=False,
                        showgrid=False, zeroline=False, range=hh_range
                    ))
                st.plotly_chart(fig_cum, use_container_width=True)

            with chart_col:
                fmt = {"누적공급량(GJ)": "{:,.1f}", "평균기온(℃)": "{:.1f}", "최저기온(℃)": "{:.1f}",
                       "가정용 청구전수": "{:,.0f}", "일수": "{:.0f}"}
                fmt = {k: v for k, v in fmt.items() if k in cum_df.columns}
                st.dataframe(
                    center_style(cum_df.style.format(fmt, na_rep="-")),
                    use_container_width=True, hide_index=True
                )
                if show_hh and hh_fallback:
                    st.caption(
                        "※ 가정용 청구전수 * 표시: 해당 월 자료가 아직 없어 가장 최근 월 값을 사용 ("
                        + ", ".join(f"{k} {m}월" for k, m in hh_fallback.items()) + ")"
                    )
        else:
            st.info("비교할 누적 데이터가 없습니다.")
        
        if not this_df.empty and plan_curve_x:
            st.markdown("### 🧮 일일계획 대비 편차")
            plan_sub = pd.DataFrame({'일': plan_curve_x, 'plan_gj': plan_curve_y})
            merged = pd.merge(this_df, plan_sub, on='일', how='left')
            merged['편차_GJ'] = (merged[act_col] / 1000.0) - merged['plan_gj']
            fig2 = go.Figure()
            fig2.add_bar(x=merged["일"], y=merged['편차_GJ'], name="편차", marker_color="#FF4B4B", hovertemplate="%{y:,.0f} GJ<extra></extra>")
            
            fig2.update_layout(
                title=f"계획 대비 편차 (실적-계획)", 
                xaxis_title="일", 
                yaxis_title="편차 (GJ)", 
                margin=dict(l=10, r=10, t=40, b=10),
                xaxis=dict(dtick=1, range=[0.5, 31.5]) 
            )
            st.plotly_chart(fig2, use_container_width=True)
            
            show = merged[["일자", "plan_gj", act_col, "편차_GJ"]].copy()
            show.columns = ["일자", "계획량(GJ)", "일별실적(GJ)", "편차(GJ)"]
            
            show["일별실적(GJ)"] = show["일별실적(GJ)"] / 1000.0
            
            show["일자"] = show["일자"].dt.strftime("%Y-%m-%d")

            sum_plan = show["계획량(GJ)"].sum()
            sum_act = show["일별실적(GJ)"].sum()
            sum_diff = show["편차(GJ)"].sum()
            
            summary_row = {
                "일자": "월 누계 (Total)",
                "계획량(GJ)": sum_plan,
                "일별실적(GJ)": sum_act,
                "편차(GJ)": sum_diff
            }
            show = pd.concat([show, pd.DataFrame([summary_row])], ignore_index=True)

            show["달성률(%)"] = show.apply(
                lambda x: (x["일별실적(GJ)"] / x["계획량(GJ)"] * 100) if x["계획량(GJ)"] > 0 else 0, 
                axis=1
            )
            
            st.dataframe(
                center_style(
                    show.style.format({
                        "계획량(GJ)": "{:,.1f}", 
                        "일별실적(GJ)": "{:,.1f}", 
                        "편차(GJ)": "{:,.1f}",
                        "달성률(%)": "{:,.1f}%"
                    })
                    .apply(lambda x: ['background-color: #f0f2f6; font-weight: bold' if x.name == len(show)-1 else '' for i in x], axis=1)
                ), 
                use_container_width=True, 
                hide_index=True
            )
        
        st.markdown("---")
        st.markdown("### 💎 일별 공급량 Top 랭킹")
        month_all = df_all[df_all["월"] == sel_month].copy()
        if not month_all.empty:
            top_n = st.slider("표시할 순위 개수", 5, 50, 10, 5, key=f"{key_prefix}top_n")
            
            st.markdown(f"#### 📅 {sel_month}월 기준 Top 랭킹")
            
            if not this_df.empty:
                max_row = this_df.loc[this_df[act_col].idxmax()]
                max_val_gj = max_row[act_col] / 1000.0
                all_vals_gj = df_all[act_col] / 1000.0
                rank_total = (all_vals_gj > max_val_gj).sum() + 1
                month_vals_gj = month_all[act_col] / 1000.0
                rank_month = (month_vals_gj > max_val_gj).sum() + 1
                target_date_str = f"{int(max_row['연'])}년 {int(max_row['월'])}월 {int(max_row['일'])}일"
                
                max_temp = max_row['평균기온(℃)']
                temp_str = f"{max_temp:.1f}℃" if not pd.isna(max_temp) else "-"

                m3_col_name = "공급량(M3)" if "공급량(M3)" in max_row.index else "공급량(m3)"
                max_val_m3 = max_row.get(m3_col_name, 0) / 1000.0

                st.markdown(f"""<div style="background-color:#e0f2fe;padding:15px;border-radius:10px;border:1px solid #bae6fd;margin-bottom:20px;">
                    <h4 style="margin:0; color:#0369a1;">📢 {target_date_str} 실적 랭킹</h4>
                    <div style="font-size:16px; margin-top:5px; color:#333;">
                        공급량: <b>{max_val_gj:,.1f} GJ</b> <span style="color:#666;font-size:0.9em;">(📦 {max_val_m3:,.1f} 천m³)</span> (🌡️ 평균기온: <b>{temp_str}</b>) <br>
                        ➡️ <span style="background-color:#fff; padding:2px 8px; border-radius:5px; border:1px solid #ddd; margin-left:25px;">🏆 역대 전체 <b>{rank_total}위</b></span> 
                        <span style="background-color:#fff; padding:2px 8px; border-radius:5px; border:1px solid #ddd; margin-left:5px;">📅 역대 {sel_month}월 중 <b>{rank_month}위</b></span>
                    </div>
                </div>""", unsafe_allow_html=True)
            
            month_all["공급량_GJ"] = month_all[act_col] / 1000.0
            rank_df = month_all.sort_values("공급량_GJ", ascending=False).head(top_n).copy()
            rank_df.insert(0, "Rank", range(1, len(rank_df) + 1))
            top3 = rank_df.head(3)
            c1, c2, c3 = st.columns(3)
            cols = [c1, c2, c3]
            icons, grads = ["🥇", "🥈", "🥉"], ["linear-gradient(120deg,#eff6ff,#fef9c3)", "linear-gradient(120deg,#f9fafb,#e5e7eb)", "linear-gradient(120deg,#fff7ed,#fef9c3)"]
            for i, (_, row) in enumerate(top3.iterrows()):
                with cols[i]: 
                   _render_supply_top_card(int(row["Rank"]), row, icons[i], grads[i])
            st.dataframe(center_style(rank_df[["Rank", "공급량_GJ", "연", "월", "일", "평균기온(℃)"]].style.format({"공급량_GJ": "{:,.1f}", "평균기온(℃)": "{:,.1f}"})), use_container_width=True, hide_index=True)
            
            st.markdown("---")
            st.markdown("#### 🏆 전체 기간 Top 랭킹")
            global_top = df_all.sort_values(act_col, ascending=False).head(top_n).copy()
            global_top["공급량_GJ"] = global_top[act_col] / 1000.0
            global_top.insert(0, "Rank", range(1, len(global_top) + 1))
            
            g_top3 = global_top.head(3)
            gc1, gc2, gc3 = st.columns(3)
            gcols = [gc1, gc2, gc3]
            for i, (_, row) in enumerate(g_top3.iterrows()):
                with gcols[i]: 
                   _render_supply_top_card(int(row["Rank"]), row, icons[i], grads[i])
            
            st.dataframe(center_style(global_top[["Rank", "공급량_GJ", "연", "월", "일", "평균기온(℃)"]].style.format({"공급량_GJ": "{:,.1f}", "평균기온(℃)": "{:,.1f}"})), use_container_width=True, hide_index=True)

            st.markdown("#### 🌡️ 기온별 공급량 변화 (3차 다항식)")
            temp_supply = month_all.dropna(subset=["평균기온(℃)", act_col]).copy()
            temp_supply = temp_supply[temp_supply[act_col] > 100]
            fig3 = go.Figure()
            if not temp_supply.empty:
                x = temp_supply["평균기온(℃)"].values
                y = temp_supply[act_col].values / 1000.0
                fig3.add_scatter(x=x, y=y, mode="markers", name="일별 데이터", marker=dict(size=7, opacity=0.7))
                if len(temp_supply) > 4:
                    coeffs = np.polyfit(x, y, 3)
                    p = np.poly1d(coeffs)
                    xs = np.linspace(x.min() - 1, x.max() + 1, 150)
                    fig3.add_scatter(x=xs, y=p(xs), mode="lines", name="3차 다항 회귀", line=dict(color="#FF4B4B", width=2))
            fig3.update_layout(title=f"{sel_month}월 기온별 공급량", xaxis_title="기온(℃)", yaxis_title="공급량 (GJ)", margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig3, use_container_width=True)
        
        st.markdown("---")
        temperature_matrix(day_df, sel_month, key_prefix + "temp_")

        st.markdown("---")
        hourly_temperature_section(key_prefix + "hourly_")
        st.markdown("---")

        temperature_supply_band_section(day_df, sel_month, key_prefix + "band_")

    st.sidebar.header("📂 [분석] 데이터 파일")
    st.sidebar.caption(plan_source_caption())
    DEFAULT_SUPPLY_XLSX = "공급량(계획_실적).xlsx"
    uploaded_analysis = st.sidebar.file_uploader("공급량 엑셀 업로드", type=['xlsx'], key="u2")
    
    supply_bytes = None
    if uploaded_analysis:
        supply_bytes = uploaded_analysis.getvalue()
        st.sidebar.success("✅ 분석 파일 로드 성공")
    else:
        try:
            path = Path(__file__).parent / DEFAULT_SUPPLY_XLSX
            if path.exists():
                supply_bytes = path.read_bytes()
                st.sidebar.info(f"ℹ️ 기본 분석 파일 사용 ({DEFAULT_SUPPLY_XLSX})")
            else:
                st.sidebar.warning(f"기본 분석 파일({DEFAULT_SUPPLY_XLSX})이 없습니다.")
        except:
            pass

    st.title("📊 도시가스 공급량 분석 (일별)")

    if supply_bytes:
        month_df, day_df = load_supply_sheets(supply_bytes)
        month_df = clean_supply_month_df(month_df)
        day_df = clean_supply_day_df(day_df)

        if month_df.empty or day_df.empty:
            st.error("엑셀 파일에 '월별계획_실적' 또는 '일별실적' 시트가 비어있거나 없습니다.")
        else:
            act_col = "실적_공급량(MJ)"
            long_dummy = month_df[["연", "월"]].copy()
            long_dummy["계획/실적"] = "실적"
            long_dummy["값"] = pd.to_numeric(month_df[act_col], errors="coerce")
            long_dummy = long_dummy.dropna(subset=["값"])
            sel_year, sel_month, years_all = render_section_selector_daily(long_dummy, "공급량(일) 기준 선택", "supplyD_base_")
            st.markdown("---")
            supply_daily_main_logic(day_df, month_df, sel_year, sel_month, key_prefix="supplyD_")
    else:
        st.info("👈 좌측 사이드바에서 '공급량(계획_실적).xlsx' 파일을 업로드해주세요.")


# ==============================================================================
# [메인 실행] 사이드바 네비게이션
# ==============================================================================
st.sidebar.title("통합 메뉴")
menu = st.sidebar.radio("이동", ["1. 도시가스 공급실적 관리", "2. 공급량 분석"])

if menu == "1. 도시가스 공급실적 관리":
    run_tab1_management()
else:
    run_tab2_analysis()
