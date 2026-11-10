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

# (달성률 카드는 아래 kpi_card()로 직접 그립니다)

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

# 2026년 사업계획 월 평균기온(℃) — 연도별 누적 공급량 차트에 점선으로 표시
PLAN_TEMP_2026 = {
    1: 1.1, 2: 4.7, 3: 9.8, 4: 15.0, 5: 19.1, 6: 24.4,
    7: 27.2, 8: 27.9, 9: 22.5, 10: 16.0, 11: 10.0, 12: 2.4,
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
        # 공급량(M3): 이상기온 판별 그래프의 점 크기용 (정확히 '공급량(M3)' 열 우선, 없으면 '실적…M3' 열)
        m3_src = "공급량(M3)" if "공급량(M3)" in df.columns else next(
            (c for c in df.columns if "실적" in c and "M3" in c.upper()), None)
        df["공급량(M3)"] = (pd.to_numeric(df[m3_src].astype(str).str.replace(",", ""), errors="coerce")
                          if m3_src is not None else np.nan)
        return df[["일자", "연도", "월", "일", "평균기온(℃)", "최저기온(℃)", "공급량(M3)"]]
    except Exception:
        return None


# ─────────────────────────────────────────────────────────
# [공통 함수 3-1] 이상기온 판별 (한국가스공사 기준)
#  - 과거 7년 중 최고·최저를 뺀 5년의 평균·표준편차를 구해, |기준값 - 5년평균| > 표준편차 이면 이상기온
#  - 월 판별: 월 평균기온 / 일 판별: 같은 월·일의 과거 7년 일평균기온
# ─────────────────────────────────────────────────────────
ABN_BG = {"high": "#FFD6D6", "low": "#D4E6FF", "normal": "#F0F2F6", None: "#F0F2F6"}   # 카드 배경(이상고온=붉은색, 이상저온=푸른색)
ABN_TXT = {"high": "#C62828", "low": "#1565C0", "normal": "#31333F", None: "#31333F"}
ABN_LABEL = {"high": "이상고온 ▲", "low": "이상저온 ▼", "normal": "정상", None: "-"}


def _five_year_judge(curr: float, past: pd.Series):
    """past: 과거 7년 값(index=연도). 반환: dict 또는 None"""
    past = past.dropna()
    if len(past) < 7:
        return None
    p5 = past.drop(index=[past.idxmax(), past.idxmin()])
    mean5 = round(float(p5.mean()), 1)
    std5 = float(np.sqrt(np.sum((p5 - mean5) ** 2) / 5))
    is_abn = abs(curr - mean5) > std5
    kind = ("high" if curr > mean5 else "low") if is_abn else "normal"
    return dict(curr=curr, mean7=float(past.mean()), mean5=mean5, std5=std5,
                lower=mean5 - std5, upper=mean5 + std5, is_abnormal=is_abn, kind=kind, past=past)


def abnormal_month_stats(ts, year: int, month: int, upto_day=None):
    """월 평균기온 이상기온 판별. upto_day를 주면 모든 연도를 1~upto_day일 평균으로 비교(같은 기간 비교)."""
    if ts is None or ts.empty:
        return None
    d = ts[ts["월"] == month]
    if upto_day is not None:
        d = d[d["일"] <= upto_day]
    avg = d.groupby("연도")["평균기온(℃)"].mean().dropna()
    if year not in avg.index:
        return None
    res = _five_year_judge(round(float(avg[year]), 1), avg[(avg.index >= year - 7) & (avg.index < year)])
    if res is None:
        return None
    res["supply"] = d.groupby("연도")["공급량(M3)"].sum(min_count=1).to_dict()
    res["avg_all"] = avg
    res["year"], res["month"], res["upto_day"] = year, month, upto_day
    return res


def abnormal_day_stats(ts, date, temp):
    """조회일 평균기온이 같은 월·일의 과거 7년 대비 이상기온인지 판별"""
    if ts is None or ts.empty or temp is None or pd.isna(temp):
        return None
    d = ts[(ts["월"] == date.month) & (ts["일"] == date.day) &
           (ts["연도"] >= date.year - 7) & (ts["연도"] < date.year)]
    past = d.dropna(subset=["평균기온(℃)"]).drop_duplicates("연도", keep="last").set_index("연도")["평균기온(℃)"]
    return _five_year_judge(round(float(temp), 1), past)


def build_abnormal_figure(st_m: dict) -> go.Figure:
    """과거 7년(회색 원) · 작년(보라 마름모) · 기준연도(주황 원)를 5년 평균±표준편차 밴드 위에 표시. 점 크기 = 공급량"""
    year, past = st_m["year"], st_m["past"]
    supply = st_m["supply"]

    def get_supply(y):
        v = supply.get(y)
        return 0 if v is None or pd.isna(v) else float(v)

    valid = [get_supply(y) for y in st_m["avg_all"].index if get_supply(y) > 0]
    max_s, min_s = (max(valid), min(valid)) if valid else (1, 0)

    def scale_size(v):
        if v == 0 or max_s == min_s:
            return 15
        return 15 + ((v - min_s) / (max_s - min_s)) * 35

    lower, upper, mean5, curr = st_m["lower"], st_m["upper"], st_m["mean5"], st_m["curr"]
    fig = go.Figure()
    fig.add_vrect(x0=lower, x1=upper, fillcolor="#00BFFF", opacity=0.1, layer="below",
                  line_width=1, line_dash="solid", line_color="#00BFFF")
    # 하한/상한: 소수 1자리, 밴드(네모칸) 위쪽 모서리 안쪽에 표시 (글자 13 → 18)
    fig.add_annotation(x=lower, y=1, xref="x", yref="paper", text=f"<b>하한 {lower:.1f}℃</b>", showarrow=False,
                       font=dict(color="#00A3E0", size=18), xanchor="left", yanchor="top", xshift=6, yshift=-4)
    fig.add_annotation(x=upper, y=1, xref="x", yref="paper", text=f"<b>상한 {upper:.1f}℃</b>", showarrow=False,
                       font=dict(color="#00A3E0", size=18), xanchor="right", yanchor="top", xshift=-6, yshift=-4)
    fig.add_vline(x=mean5, line=dict(color="#2ca02c", width=2, dash="dash"),
                  annotation_text=f"5년 평균 ({mean5:.1f}℃)", annotation_position="bottom right",
                  annotation_font=dict(color="#2ca02c"))

    sizes, texts, xs = [], [], []
    for y, t in past.items():
        y = int(y)
        if y == year - 1:
            continue
        sv = get_supply(y)
        sizes.append(scale_size(sv))
        texts.append(f"<b>{y}년</b><br>평균기온: {t:.1f}℃<br>공급량: {sv:,.0f} M3")
        xs.append(t)
    fig.add_trace(go.Scatter(
        x=xs, y=[0] * len(xs), mode="markers", name="과거 7년",
        marker=dict(size=sizes, color="rgba(128, 128, 128, 0.5)", line=dict(color="gray", width=1)),
        hoverinfo="text", text=texts))

    y1 = year - 1
    if y1 in past.index:
        y1v, y1s = float(past[y1]), get_supply(y1)
        fig.add_trace(go.Scatter(
            x=[y1v], y=[0], mode="markers+text", name=f"작년({y1}년)",
            marker=dict(size=scale_size(y1s), color="#9467bd", symbol="diamond", line=dict(color="white", width=2)),
            text=[f"<b>{y1}년 ({y1v:.1f}℃)</b>"], textposition="top center", textfont=dict(size=13, color="#9467bd"),
            hoverinfo="text", hovertext=f"<b>{y1}년</b><br>평균기온: {y1v:.1f}℃<br>공급량: {y1s:,.0f} M3"))

    cs = get_supply(year)
    fig.add_trace(go.Scatter(
        x=[curr], y=[0], mode="markers+text", name=f"{year}년",
        marker=dict(size=scale_size(cs), color="#FF8C00", symbol="circle", line=dict(color="white", width=2)),
        text=[f"<b>{year}년 ({curr}℃)</b>"], textposition="bottom center", textfont=dict(size=15, color="#FF8C00"),
        hoverinfo="text", hovertext=f"<b>{year}년</b><br>평균기온: {curr:.1f}℃<br>공급량: {cs:,.0f} M3"))

    fig.update_layout(
        height=320,
        yaxis=dict(showticklabels=False, range=[-1.3, 1.3], showgrid=False, zeroline=False),
        xaxis=dict(title="평균기온(℃)", gridcolor="#f0f0f0", showline=True, linecolor="lightgray"),
        showlegend=False, margin=dict(l=40, r=40, t=20, b=40), plot_bgcolor="white")
    return fig


def render_abnormal_section(st_m, month: int, same_window: bool, upto_day: int):
    """[열량 실적 하단] 이상기온 판별 상세 (한국가스공사 기준)"""
    st.header(f"🚨 {month}월 이상기온 판별 상세 (한국가스공사 기준)")
    st.toggle(f"같은 기간(1~{upto_day}일)끼리 비교", value=False, key="abn_same_window",
              help="끄면 당월은 현재까지 평균, 과거 연도는 월 전체 평균과 비교합니다(기존 방식). "
                   "켜면 과거 연도도 같은 1~N일 평균으로 비교해 월 중간에도 공정하게 판별합니다.")
    if st_m is None:
        st.info("이상기온 판별에 필요한 과거 7년 기온 자료가 부족하거나 구글시트 기온을 읽지 못했습니다.")
        return
    yr, mo = st_m["year"], st_m["month"]
    if st_m["is_abnormal"]:
        st.error(f"🚨 **주의:** {yr}년 {mo}월은 가스공사 기준 **'이상기온'**으로 판별되었습니다! (도시가스 실적 변동에 유의하세요)", icon="🚨")
    else:
        st.success(f"✅ {yr}년 {mo}월은 가스공사 기준 **'정상 기온'** 범위 내에 있습니다.", icon="✅")
    st.write("")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("최근 7년 평균", f"{st_m['mean7']:.1f}℃")
    c2.metric("5년 평균 (최대/최소 제외)", f"{st_m['mean5']:.1f}℃")
    c3.metric("5년 표준편차", f"{st_m['std5']:.2f}")
    c4.metric(f"기준 연도({yr}) 평균", f"{st_m['curr']:.1f}℃",
              delta="이상기온 발생!" if st_m["is_abnormal"] else "정상 범위",
              delta_color="inverse" if st_m["is_abnormal"] else "normal")
    st.plotly_chart(build_abnormal_figure(st_m), use_container_width=True)
    if same_window:
        st.caption(f"※ 모든 연도를 {mo}월 1~{upto_day}일 평균기온으로 비교했습니다. 점 크기=같은 기간 공급량(M3)")
    else:
        st.caption(f"※ {yr}년은 현재까지 자료 평균, 과거 연도는 {mo}월 전체 평균입니다. 점 크기=월 공급량(M3). "
                   "월 초·중순에는 위 '같은 기간 비교'를 켜면 더 정확합니다.")


def kpi_card(label: str, rate: float, value_txt: str, delta_val: float, plan_txt: str,
             bg: str = "#F0F2F6", right_html: str = "") -> str:
    """달성률 카드(HTML). 기존 st.metric과 같은 크기, 배경색만 이상기온 판별 결과에 따라 변경"""
    up = delta_val >= 0
    d_color, d_bg = ("#09AB3B", "rgba(33,195,84,0.12)") if up else ("#FF2B2B", "rgba(255,43,43,0.10)")
    arrow = "↑" if up else "↓"
    return (
        f'<div style="background:{bg};border-radius:10px;padding:18px 20px;min-height:200px;display:flex;'
        f'justify-content:space-between;align-items:center;gap:12px;">'
        f'<div><div style="font-size:14px;line-height:1.3;color:#31333F;">{label} <span style="font-size:16.8px;">{rate:.1f}%</span></div>'
        f'<div style="font-size:36px;line-height:1.3;color:#31333F;margin-top:6px;">{value_txt}</div>'
        f'<div style="margin-top:6px;"><span style="font-size:14px;color:{d_color};background:{d_bg};'
        f'border-radius:12px;padding:2px 8px;">{arrow} {delta_val:+,.0f} GJ</span></div>'
        f'<div style="font-size:13px;color:#808495;margin-top:10px;">{plan_txt}</div></div>'
        f'{right_html}</div>'
    )


# ─────────────────────────────────────────────────────────
# [공통 함수 3-2] 기온–공급량 관계(HeatBand 방식) : 3차 다항 회귀 + 난방 시작(힌지) 구간
#  - 과거 일별 공급량(MJ)과 일평균기온으로 Q = a + b·T + c·T² + d·T³ 적합
#  - 1℃ 변화에 따른 공급량 변화(MJ/℃) = −dQ/dT
# ─────────────────────────────────────────────────────────
HEAT_FONT = "NanumGothic, Arial, Noto Sans KR, sans-serif"


def _smooth_relu(x, eps):
    return 0.5 * (x + np.sqrt(x * x + eps * eps))


def _nice_poly_string(a, b, c, d, digits=1):
    def term(v, sfx, lead=False):
        if abs(v) < 1e-12:
            return ""
        sign = "" if lead and v >= 0 else (" - " if v < 0 else " + ")
        return f"{sign}{abs(v):,.{digits}f}{sfx}"
    return "y = " + term(d, "·T³", lead=True) + term(c, "·T²") + term(b, "·T") + term(a, "")


@st.cache_data(show_spinner=False, ttl=600)
def build_heat_model(temp: np.ndarray, q_mj: np.ndarray):
    T = np.asarray(temp, dtype=float)
    Q = np.asarray(q_mj, dtype=float)
    if len(T) < 30:
        return None
    coef = np.polyfit(T, Q, 3)
    d, c, b, a = [float(x) for x in coef]
    yhat = np.polyval(coef, T)
    ss_tot = float(np.sum((Q - Q.mean()) ** 2))
    r2 = 1.0 - float(np.sum((Q - yhat) ** 2)) / ss_tot if ss_tot > 0 else np.nan
    p1, p99 = np.percentile(T, 1), np.percentile(T, 99)
    xmin_vis = float(np.floor(min(-5, p1 - 1.5)))
    xmax_vis = float(np.ceil(max(25, p99 + 1.5)))
    tgrid = np.linspace(xmin_vis, xmax_vis, 1201)
    deriv = b + 2 * c * tgrid + 3 * d * tgrid ** 2
    eps_rel = 0.015 * max(1.0, float(np.nanmax(np.abs(deriv))))
    inc = _smooth_relu(-deriv, eps_rel)
    T_slow = float(tgrid[int(np.argmin(deriv))])
    max_neg = float(np.max(inc))
    T_cap = float(tgrid[np.argmax(inc <= 0.02 * max_neg)]) if max_neg > 0 else np.nan
    # 난방 시작 기온 θ* (힌지 회귀: 0~20℃를 0.1℃ 간격으로 탐색)
    best = (np.nan, np.inf)
    for th in np.arange(0.0, 20.0 + 1e-9, 0.1):
        X = np.column_stack([np.ones_like(T), np.clip(th - T, 0, None)])
        beta, *_ = np.linalg.lstsq(X, Q, rcond=None)
        rmse = float(np.sqrt(np.mean((Q - X @ beta) ** 2)))
        if rmse < best[1]:
            best = (float(th), rmse)
    theta = best[0]
    H = np.clip(theta - T, 0, None)
    beta_c, *_ = np.linalg.lstsq(np.column_stack([np.ones_like(H), H, H ** 2, H ** 3]), Q, rcond=None)
    return dict(a=a, b=b, c=c, d=d, r2=r2, xmin=xmin_vis, xmax=xmax_vis, eps=eps_rel, T_slow=T_slow, T_cap=T_cap,
                theta=theta, hinge=[float(x) for x in beta_c], mean_temp=float(T.mean()),
                eq=_nice_poly_string(a, b, c, d))


def heat_q(model, t):
    """기온 t에서의 예측 공급량(MJ)"""
    t = np.asarray(t, dtype=float)
    return model["a"] + model["b"] * t + model["c"] * t ** 2 + model["d"] * t ** 3


def heat_band_mean(model, lo, hi):
    """lo~hi℃ 구간의 1℃ 하락당 평균 공급량 증가(MJ/℃)"""
    t = np.arange(lo, hi + 0.001, 0.1)
    d1 = model["b"] + 2 * model["c"] * t + 3 * model["d"] * t ** 2
    return float(np.mean(_smooth_relu(-d1, model["eps"])))


def build_heat_fig_demand(model, T, Q) -> go.Figure:
    """B. Heating Start / Slowdown — 수요곡선"""
    xmin, xmax, theta, T_slow, T_cap = model["xmin"], model["xmax"], model["theta"], model["T_slow"], model["T_cap"]
    tline = np.linspace(xmin, xmax, 600)
    a_c, b_c, c_c, d_c = model["hinge"]
    Hl = np.clip(theta - tline, 0, None)
    qcurve = a_c + b_c * Hl + c_c * Hl ** 2 + d_c * Hl ** 3
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=T, y=Q, mode="markers", name="전체(참고)", marker=dict(size=3, color="lightgray"), opacity=0.3))
    fig.add_trace(go.Scatter(x=T, y=Q, mode="markers", name="학습", marker=dict(size=4), marker_color="orange", opacity=0.6))
    fig.add_trace(go.Scatter(x=tline, y=qcurve, mode="lines", name="힌지(곡선) 적합",
                             line=dict(width=3, shape="spline", smoothing=1.1)))
    note = dict(xref="x", yref="paper", showarrow=False, font=dict(size=12), bgcolor="rgba(255,255,255,0.7)",
                bordercolor="rgba(0,0,0,0.1)")
    fig.add_vrect(x0=xmin, x1=theta, fillcolor="LightSkyBlue", opacity=0.18, line_width=0, layer="below")
    fig.add_annotation(x=(xmin + theta) / 2, y=1.12, text="난방 시작 구간 (Heating Start)", **note)
    fig.add_vrect(x0=xmin, x1=T_slow, fillcolor="LightCoral", opacity=0.14, line_width=0, layer="below")
    fig.add_annotation(x=(xmin + T_slow) / 2, y=1.12,
                       text=f"난방 포화 구간 (총 사용량 증가, 증가폭은 둔화 ≤ {T_slow:.2f}℃)", **note)
    fig.add_vline(x=theta, line_dash="dash")
    fig.add_annotation(x=theta, y=1.14, text=f"Start θ* = {theta:.2f}℃", **note)
    if np.isfinite(T_cap):
        fig.add_vline(x=T_cap, line_dash="dot")
        fig.add_annotation(x=T_cap, y=1.10, text=f"Saturation {T_cap:.2f}℃", **note)
    fig.update_layout(template="simple_white", font=dict(family=HEAT_FONT, size=14),
                      margin=dict(l=40, r=20, t=60, b=70),
                      xaxis=dict(title="기온(℃)", range=[xmin, xmax]),
                      yaxis=dict(title="공급량(MJ)", tickformat=","),
                      legend=dict(orientation="h", yanchor="top", y=-0.18, x=0.01))
    return fig


def plan_temp_3yr(ts, date):
    """일일계획의 기준 기온 = 최근 3년 같은 월·일의 평균기온 (구글시트)"""
    if ts is None or ts.empty:
        return np.nan
    d = ts[(ts["월"] == date.month) & (ts["일"] == date.day) &
           (ts["연도"] >= date.year - 3) & (ts["연도"] < date.year)]
    v = d["평균기온(℃)"].dropna()
    return float(v.mean()) if len(v) else np.nan


def effect_segments(model, t_plan, t_act):
    """실적 기온이 속한 5℃ 구간(예: 8.7℃ → 5~10℃)의 1℃당 변화량 하나만 사용해 (기온 차이 × 변화량)을 계산.
    계획보다 추우면 +, 따뜻하면 −. 반환: (구간 리스트[1개], 기온효과 GJ)"""
    t_act, t_plan = float(t_act), float(t_plan)
    b_lo = float(np.floor(t_act / 5.0 + 1e-9) * 5.0)
    bl = min(max(b_lo, model["xmin"]), model["xmax"] - 5.0)
    slope = heat_band_mean(model, bl, bl + 5.0) / 1000.0      # GJ/℃ (C 요약표와 같은 값)
    dt = t_plan - t_act
    seg = dict(lo=min(t_act, t_plan), hi=max(t_act, t_plan), band=(b_lo, b_lo + 5.0), dT=abs(dt), slope=slope, eff=dt * slope)
    return [seg], dt * slope


def render_temp_effect_box(model, ts, target_date, day_temp, act_d, plan_d):
    """당일 계획 대비 증감을 '기온 효과'와 '기온 외 효과'로 나눠 간단한 표로 보여준다"""
    st.markdown("#### 🌡️ 계획 대비 증감, 왜 그럴까요?")
    if model is None:
        st.info("기온–공급량 관계를 계산할 과거 자료가 부족합니다.")
        return
    t_plan = plan_temp_3yr(ts, target_date)
    if pd.isna(day_temp) or pd.isna(t_plan) or plan_d <= 0 or act_d <= 0:
        st.info("조회일의 계획·실적·평균기온 중 비어 있는 값이 있어 설명을 만들 수 없습니다.")
        return
    t_act = float(day_temp)
    diff = act_d - plan_d
    dt = t_plan - t_act                       # +이면 계획보다 더 추웠음
    segs, eff = effect_segments(model, t_plan, t_act)
    other = diff - eff
    avg_slope = eff / dt if abs(dt) >= 0.05 else (segs[0]["slope"] if segs else 0.0)

    word = "많이" if diff >= 0 else "적게"
    st.markdown(f"**{target_date.month}/{target_date.day}** 공급은 계획보다 **{abs(diff):,.0f} GJ {word}** 나갔습니다 "
                f"({act_d / plan_d * 100:.1f}%). 기온 영향으로 **약 {abs(eff):,.0f} GJ "
                f"{'증가' if eff >= 0 else '감소'}**했습니다.")
    rows = [
        ("계획 / 실적", f"{plan_d:,.0f} → {act_d:,.0f} GJ ({diff:+,.0f})"),
        ("기온", f"계획 {t_plan:.1f}℃, 실적 {t_act:.1f}℃ ({abs(dt):.1f}℃ 차이)"),
        ("1℃당 변화량", f"약 {avg_slope:,.0f} GJ/℃"),
        ("기온 효과", f"{abs(dt):.1f}℃ × {avg_slope:,.0f} GJ/℃ ≈ <b>{eff:+,.0f} GJ</b>"),
        ("기온 외 효과", f"{diff:,.0f} − ({eff:,.0f}) ≈ <b>{other:+,.0f} GJ</b>"),
    ]
    def _bg(label):    # 기온 효과 줄은 푸른색 배경으로 강조
        return "background:#D4E6FF;" if label == "기온 효과" else ""
    tr = "".join(
        f"<tr style='{_bg(a)}'><td style='padding:10px 8px;border-bottom:1px solid #eee;font-weight:600;white-space:nowrap;'>{a}</td>"
        f"<td style='padding:10px 8px;border-bottom:1px solid #eee;'>{b}</td></tr>" for a, b in rows)
    st.markdown(
        "<table style='width:100%;border-collapse:collapse;font-size:15px;'>"
        "<thead><tr><th style='text-align:left;padding:10px 8px;border-bottom:2px solid #ddd;background:#F0F2F6;'>항목</th>"
        "<th style='text-align:left;padding:10px 8px;border-bottom:2px solid #ddd;background:#F0F2F6;'>값</th></tr></thead>"
        f"<tbody>{tr}</tbody></table>", unsafe_allow_html=True)

    # 계산 과정: 실적 기온 구간 값(표에 사용) + 계획 기온 구간 값(참고) 비교
    with st.expander("계산 과정 보기"):
        sg = segs[0]
        a_lo, a_hi, slope_a = sg["band"][0], sg["band"][1], sg["slope"]
        p_lo = float(np.floor(t_plan / 5.0 + 1e-9) * 5.0)
        pl = min(max(p_lo, model["xmin"]), model["xmax"] - 5.0)
        slope_p = heat_band_mean(model, pl, pl + 5.0) / 1000.0
        eff_p = dt * slope_p
        th = "padding:8px;border-bottom:2px solid #ddd;text-align:right;background:#F0F2F6;"
        td = "padding:8px;border-bottom:1px solid #eee;text-align:right;"
        use = "background:#D4E6FF;font-weight:700;"
        body = (
            f"<tr style='{use}'><td style='{td}text-align:left;'>실적 기온 기준 (표에 사용)</td>"
            f"<td style='{td}'>{t_act:.1f}℃</td><td style='{td}'>{a_lo:g}~{a_hi:g}℃</td>"
            f"<td style='{td}'>{slope_a:,.0f} GJ/℃</td>"
            f"<td style='{td}'>{abs(dt):.1f}℃ × {slope_a:,.0f} = {eff:+,.0f} GJ</td></tr>"
            f"<tr style='background:#F0F2F6;font-weight:700;'><td style='{td}text-align:left;'>계획 대비 증감</td>"
            f"<td style='{td}'></td><td style='{td}'></td><td style='{td}'></td><td style='{td}'>{diff:+,.0f} GJ</td></tr>"
            f"<tr><td style='{td}text-align:left;'>계획 기온 기준 (참고)</td>"
            f"<td style='{td}'>{t_plan:.1f}℃</td><td style='{td}'>{p_lo:g}~{p_lo + 5:g}℃</td>"
            f"<td style='{td}'>{slope_p:,.0f} GJ/℃</td>"
            f"<td style='{td}'>{abs(dt):.1f}℃ × {slope_p:,.0f} = {eff_p:+,.0f} GJ</td></tr>"
            f"<tr><td style='{td}text-align:left;'>기온 외 효과 (나머지)</td><td style='{td}'></td><td style='{td}'></td>"
            f"<td style='{td}'></td><td style='{td}'>{other:+,.0f} GJ</td></tr>")
        st.markdown(
            "<table style='width:100%;border-collapse:collapse;font-size:14px;'><thead><tr>"
            f"<th style='{th}text-align:left;'>구분</th><th style='{th}'>기온</th><th style='{th}'>기온 구간</th>"
            f"<th style='{th}'>1℃당 변화량</th><th style='{th}'>기온 차이 × 변화량 = 기온 효과</th></tr></thead>"
            f"<tbody>{body}</tbody></table>", unsafe_allow_html=True)
        if (a_lo, a_hi) != (p_lo, p_lo + 5.0):
            lo_e, hi_e = sorted([eff, eff_p], key=abs)
            st.markdown(
                f"**구간이 다릅니다.** 실적 기온 {t_act:.1f}℃는 **{a_lo:g}~{a_hi:g}℃ 구간**, 계획 기온 {t_plan:.1f}℃는 "
                f"**{p_lo:g}~{p_lo + 5:g}℃ 구간**입니다. 기온이 낮은 구간일수록 1℃ 내려갈 때 늘어나는 공급량이 커서 "
                f"({slope_a:,.0f} vs {slope_p:,.0f} GJ/℃), 어느 구간 값을 쓰느냐에 따라 기온 효과가 "
                f"{abs(lo_e):,.0f} ~ {abs(hi_e):,.0f} GJ로 달라집니다. 이 화면은 **실제 기온 구간** 값을 사용했습니다.")
        else:
            st.markdown(f"계획 기온과 실적 기온이 같은 **{a_lo:g}~{a_hi:g}℃ 구간**이라 1℃당 변화량이 같습니다.")
    st.caption("※ 계획 기온 = 일일계획 기준(최근 3년 같은 날 평균기온). 1℃당 변화량은 아래 '1도 변화에 따른 공급량 변화'의 "
               "구간별 값과 같습니다. 기온 외 효과에는 요일·휴일, 고객 증가, 계획 오차 등이 포함됩니다.")


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


# ─────────────────────────────────────────────────────────
# [공통 함수 4-1] 시간대별 공급량 (HOURLY_SUPPLY*.csv / .xlsx)
#  - 열: 일자, 시(1~24), 공급량(m3)  ← 공급량현황 '합계' 아래 '가스공사' 시간별 값
#  - 파일 이름은 HOURLY_SUPPLY 로 시작하면 뒤는 무엇이든 가능, 여러 개면 합치고 겹치면 최신 파일 우선
# ─────────────────────────────────────────────────────────
def _supply_files() -> List[Path]:
    base = Path(__file__).parent
    files = [p for p in base.iterdir() if p.is_file() and p.suffix.lower() in (".csv", ".xlsx")
             and p.name.upper().startswith("HOURLY_SUPPLY")]
    return sorted(files, key=lambda p: (p.name, p.stat().st_mtime))


def _supply_signature():
    return tuple((p.name, p.stat().st_mtime) for p in _supply_files())


def _read_supply_file(path: Path) -> Optional[pd.DataFrame]:
    raws = []
    if path.suffix.lower() == ".xlsx":
        try:
            raws.append(pd.read_excel(path))
        except Exception:
            return None
    else:
        for enc in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                raws.append(pd.read_csv(path, encoding=enc))
                break
            except Exception:
                continue
    for raw in raws:
        raw.columns = [str(c).strip() for c in raw.columns]
        if len(raw.columns) < 3:
            continue
        c_d = next((c for c in raw.columns if "일자" in c or "날짜" in c), raw.columns[0])
        c_h = next((c for c in raw.columns if c == "시" or "시간" in c), raw.columns[1])
        c_v = next((c for c in raw.columns if "가스공사" in c or "공급" in c), raw.columns[2])
        out = pd.DataFrame({
            "일자": pd.to_datetime(raw[c_d], errors="coerce").dt.normalize(),
            "시": pd.to_numeric(raw[c_h].astype(str).str.extract(r"(\d+)")[0], errors="coerce"),
            "supply": pd.to_numeric(raw[c_v].astype(str).str.replace(",", ""), errors="coerce"),
        }).dropna()
        out = out[(out["시"] >= 1) & (out["시"] <= 24)]
        out["시"] = out["시"].astype(int)
        return out
    return None


@st.cache_data(show_spinner=False, ttl=600)
def load_hourly_supply(signature):
    """(일자, 시, supply[m3]) 반환. 없으면 None"""
    frames = [f for f in (_read_supply_file(p) for p in _supply_files()) if f is not None and not f.empty]
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True).drop_duplicates(["일자", "시"], keep="last")
    return df.sort_values(["일자", "시"]).reset_index(drop=True)


def _apply_supply_layout(fig: go.Figure, y_lo: float, y_hi: float, ymax: float):
    """기온(좌측 축)과 공급량 막대(우측 축)를 한 그래프에 합침. 막대는 아래쪽 약 30%에 깔리도록 축 범위를 잡는다."""
    ext = (y_hi - y_lo) * 0.45                       # 기온 축 아래로 여백을 만들어 막대 자리 확보
    step_t = 2 if (y_hi - y_lo) <= 24 else 5
    t_ticks = [v for v in range(int(np.ceil(y_lo / step_t)) * step_t, int(y_hi) + 1, step_t)]   # 기온 눈금은 실제 기온 구간만
    step_s = 50000 if ymax > 120000 else 20000
    s_ticks = list(range(0, int(ymax // step_s + 2) * step_s, step_s))
    fig.update_layout(
        margin=dict(l=10, r=10, t=50, b=40),
        yaxis=dict(range=[y_lo - ext, y_hi], tickmode="array", tickvals=t_ticks, automargin=True),
        yaxis2=dict(overlaying="y", side="right", range=[0, ymax / 0.30], showgrid=False, showline=False,
                    zeroline=False, tickmode="array", tickvals=s_ticks, ticktext=[f"{v:,}" for v in s_ticks],
                    tickfont=dict(color=_AXIS_TXT, size=11), automargin=True,
                    title=dict(text="공급량 (m³)", font=dict(color=_AXIS_TXT, size=12))),
        barmode="group", bargap=0.25, bargroupgap=0.05,
    )


def _supply_by_day(supply: Optional[pd.DataFrame]) -> dict:
    if supply is None or supply.empty:
        return {}
    return {pd.Timestamp(d): g.sort_values("시") for d, g in supply.groupby("일자")}


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


def build_hourly_compare_figure(days: list, supply_days: Optional[dict] = None) -> go.Figure:
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

    if supply_days:
        ymax = 1.0
        for i in range(len(days) - 1, -1, -1):          # 과거일 → 최신일 순으로 그려 최신일 막대가 맨 앞/오른쪽
            dd = days[i]
            g = supply_days.get(pd.Timestamp(dd["date"]))
            if g is None or g.empty:
                continue
            ymax = max(ymax, float(g["supply"].max()))
            fig.add_trace(go.Bar(
                x=g["시"], y=g["supply"], yaxis="y2", name=f"{dd['label']} 공급량(m³, 우측 축)", showlegend=(i == 0),
                marker=dict(color=_rgba(dd["color"], 0.55 if i == 0 else 0.28)),
                hovertemplate=f"{dd['label']} {dd['tag']} %{{x}}시<br>공급량 %{{y:,.0f}} m³<extra></extra>",
            ))

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
    if supply_days:
        _apply_supply_layout(fig, y_lo, y_hi, ymax)
    return fig


def build_hourly_continuous_figure(obs_m: pd.DataFrame, days: list, sheet_avg: dict,
                                   supply: Optional[pd.DataFrame] = None) -> go.Figure:
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
    sup_max = None
    if supply is not None and not supply.empty:
        sm = supply[supply["일자"] >= pd.Timestamp(obs_m["dt"].min()).normalize()].copy()
        if not sm.empty:
            sm["dt"] = sm["일자"] + pd.to_timedelta(sm["시"], unit="h")       # 24시 = 다음날 00:00
            sup_max = float(sm["supply"].max())
            fig.add_trace(go.Bar(
                x=sm["dt"], y=sm["supply"], yaxis="y2", name="시간별 공급량(가스공사)", showlegend=True,
                marker=dict(color=_rgba(_DAY_COLORS[0], 0.55)), width=3600 * 1000 * 0.8,
                hovertemplate="%{x|%m/%d %H:%M}<br>공급량 %{y:,.0f} m³<extra></extra>",
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
    if sup_max:
        _apply_supply_layout(fig, y_lo, y_hi, sup_max)
        fig.update_layout(barmode="overlay")
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

    # '최신일' = 24시간이 모두 들어온 마지막 날 (아직 진행 중인 날은 제외 → 전날과 공정하게 비교)
    cnt = obs.groupby("일자")["시"].nunique()
    full_days = cnt[cnt >= 24].index
    last_day = pd.Timestamp(full_days.max() if len(full_days) else obs["일자"].max())
    partial_day = pd.Timestamp(obs["일자"].max()) if pd.Timestamp(obs["일자"].max()) > last_day else None
    avail = set(pd.to_datetime(obs["일자"].unique()))
    opts = [f"D-{k}" for k in range(1, 7) if (last_day - pd.Timedelta(days=k)) in avail]
    if not opts:
        st.info("비교할 전날(D-1) 자료가 없습니다.")
        return

    # 제목 → 안내 문구 → [D-n 버튼 (좌) | 이어보기 (우)] → 그래프
    st.markdown(f"### 🌡️ 시간대별 기온 분석 · 최신 {last_day:%m/%d}")
    cap_slot = st.empty()          # 안내 문구 자리 (아래 버튼 선택값이 정해진 뒤 채움)

    try:    # 버튼들을 같은 높이로 맞춤 (구버전 streamlit은 옵션이 없어 기본 정렬)
        b_left, b_right, b_sup = st.columns([3.3, 1.2, 1.9], vertical_alignment="center")
    except TypeError:
        b_left, b_right, b_sup = st.columns([3.3, 1.2, 1.9])
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
    with b_sup:    # 그래프 우측 상단: 시간대별 공급량 비교
        show_sup = st.toggle("시간대별 공급량 비교", value=False, key=f"{key_prefix}supply",
                             help="시간대별 기온 그래프 아래에 시간별 공급량(가스공사, m³) 막대그래프를 함께 보여줍니다.")
    pick = pick or opts[0]
    n_back = int(pick.split("-")[1])
    cap_slot.caption(f"비교 기간: 최신일({last_day:%m/%d}) 기준 {pick}까지 총 {n_back + 1}일 · "
                     f"시간자료 최신 관측 {obs['dt'].max():%Y-%m-%d %H:%M}"
                     + (f" · {partial_day:%m/%d}은 아직 24시간이 모이지 않아 비교에서 제외 (이어보기에는 표시)" if partial_day is not None else "")
                     + f" · 불러온 파일 {len(_obs_asos_files())}개")

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

    supply, supply_days = None, None
    if show_sup:
        supply = load_hourly_supply(_supply_signature())
        if supply is None or supply.empty:
            st.warning("app.py와 같은 폴더에 `HOURLY_SUPPLY`로 시작하는 시간대별 공급량 파일(csv/xlsx)이 없습니다. "
                       "열: 일자, 시, 공급량(m3)  예) HOURLY_SUPPLY_20261030.csv")
            supply = None
        else:
            supply_days = _supply_by_day(supply)
            if not any(pd.Timestamp(dd["date"]) in supply_days for dd in days):
                st.info("선택한 날짜에 해당하는 시간대별 공급량 자료가 아직 없습니다.")
                supply = supply_days = None

    if cont:
        month_start = last_day.replace(day=1)
        obs_m = obs[obs["dt"] >= month_start].copy()
        st.plotly_chart(build_hourly_continuous_figure(obs_m, days, sheet_avg, supply), use_container_width=True)
        st.caption(f"{obs_m['dt'].min():%m/%d %H:%M} ~ {obs_m['dt'].max():%m/%d %H:%M} · "
                   f"색 음영=선택한 {len(days)}일(진한 부분=날짜별 최저기온 지속 구간) · 주황 점선=일평균기온(구글시트)")
    else:
        st.plotly_chart(build_hourly_compare_figure(days, supply_days), use_container_width=True)
        runs = " · ".join(f"{dd['label']} {dd['stats']['run_start']}~{dd['stats']['run_end']}시" for dd in days)
        st.caption(f"※ 음영=날짜별 최저기온에서 +{days[0]['stats']['tol']:g}℃ 이내로 이어진 구간 ({runs}) · "
                   "마름모=그날의 최저기온 · 점선·왼쪽 네모=일평균기온(구글시트) · 24시=다음날 00:00")

    def _sup_total(dd):
        g = (supply_days or {}).get(pd.Timestamp(dd["date"]))
        return None if g is None or g.empty else float(g["supply"].sum())

    tbl_rows = [{
            "날짜": dd["date"], "구분": dd["tag"],
            "평균기온(℃)": dd["avg"],
            "최저기온(℃)": dd["stats"]["tmin"], "최저 발생(시)": dd["stats"]["tmin_hour"],
            "최고기온(℃)": dd["stats"]["tmax"], "최고 발생(시)": dd["stats"]["tmax_hour"],
            "관측 시간 수": dd["n"],
        } for dd in days]
    fmt = {"평균기온(℃)": "{:.1f}", "최저기온(℃)": "{:.1f}", "최고기온(℃)": "{:.1f}"}
    if supply_days:
        for row, dd in zip(tbl_rows, days):
            row["일 공급량(m³)"] = _sup_total(dd)
        fmt["일 공급량(m³)"] = "{:,.0f}"
    st.dataframe(
        pd.DataFrame(tbl_rows).style.format(fmt, na_rep="-")
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
    if supply_days and len(days) >= 2:
        sa, sb = _sup_total(days[0]), _sup_total(days[1])
        if sa and sb:
            ga, gb = supply_days[pd.Timestamp(days[0]["date"])], supply_days[pd.Timestamp(days[1]["date"])]
            m = ga.merge(gb, on="시", suffixes=("_a", "_b"))
            m["d"] = m["supply_a"] - m["supply_b"]
            up = m.sort_values("d", ascending=False).head(3)
            hrs = ", ".join(f"{int(r['시'])}시({r['d']:+,.0f})" for _, r in up.iterrows())
            st.info(f"공급량(가스공사) {days[0]['label']} {sa:,.0f} m³ vs {days[1]['label']} {sb:,.0f} m³ "
                    f"({sa - sb:+,.0f} m³, {(sa / sb - 1) * 100:+.1f}%) · 전일 대비 증가가 큰 시간: {hrs}")
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

    # ── 이상기온 판별 (일: 같은 월·일 과거 7년 / 월: 월 평균기온) → 카드 배경색에 반영 ──
    ts_abn = load_temperature_sheet()
    same_win = bool(st.session_state.get("abn_same_window", False))
    stat_m = abnormal_month_stats(ts_abn, target_date.year, target_date.month,
                                  target_date.day if same_win else None)
    day_temp = current_row['평균기온(℃)'].iloc[0] if '평균기온(℃)' in current_row.columns else np.nan
    stat_d = abnormal_day_stats(ts_abn, target_date, day_temp)
    kind_d = stat_d["kind"] if stat_d else None
    kind_m = stat_m["kind"] if stat_m else None

    st.markdown("### 🔥 열량 실적 (GJ)")
    col_g1, col_g2, col_g3 = st.columns(3)

    with col_g1:
        diff_gj = current_val_gj - plan_val_gj
        rate_gj = (current_val_gj / plan_val_gj * 100) if plan_val_gj > 0 else 0
        t_txt = f"{float(day_temp):.1f}℃" if pd.notna(day_temp) else "-"
        norm_txt = (f"평년 {stat_d['mean5']:.1f}℃ (정상 {stat_d['lower']:.1f}~{stat_d['upper']:.1f})"
                    if stat_d else "")
        temp_html = (
            f'<div style="text-align:right;min-width:150px;">'
            f'<div style="font-size:14px;color:#555;">🌡 {target_date.month}/{target_date.day} 평균기온</div>'
            f'<div style="font-size:40px;font-weight:700;line-height:1.2;color:{ABN_TXT[kind_d]};">{t_txt}</div>'
            f'<div style="font-size:15px;font-weight:700;color:{ABN_TXT[kind_d]};">{ABN_LABEL[kind_d]}</div>'
            f'<div style="font-size:12px;color:#777;">{norm_txt}</div></div>'
        )
        st.markdown(kpi_card("일간 달성률", rate_gj, f"{int(current_val_gj):,} GJ", diff_gj,
                             f"계획: {int(plan_val_gj):,} GJ", ABN_BG[kind_d], temp_html), unsafe_allow_html=True)
        if rank_text:
            if st.toggle("랭킹확인", value=False, key="show_rank"):   # 기본: 비활성화
                st.markdown(f"<span style='font-size: 150%; color: red; font-weight: bold;'>{rank_text}</span><br><span style='font-size: 150%; color: black;'>(2014년 1월 1일 이후 랭킹)</span>", unsafe_allow_html=True)
            if is_top_rank:
                st.balloons()
                st.toast("🎉 축하합니다! 역대 최고 공급량(1위)을 달성했습니다! 🎆")

    with col_g2:
        mask_mtd = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month) & (df['날짜'] <= target_date)
        mtd_data = df[mask_mtd]
        a_mtd, p_mtd = mtd_data['실적(GJ)'].sum(), mtd_data['계획(GJ)'].sum()
        rate_mtd = (a_mtd/p_mtd*100) if p_mtd > 0 else 0
        mtd_temp = pd.to_numeric(mtd_data['평균기온(℃)'], errors='coerce').mean() if '평균기온(℃)' in mtd_data.columns else np.nan
        mtd_txt = f"{mtd_temp:.1f}℃" if pd.notna(mtd_temp) else "-"
        m_norm_txt = (f"평년 {stat_m['mean5']:.1f}℃ (정상 {stat_m['lower']:.1f}~{stat_m['upper']:.1f})"
                      if stat_m else "")
        m_html = (
            f'<div style="text-align:right;min-width:150px;">'
            f'<div style="font-size:14px;color:#555;">🌡 {target_date.month}월 1~{target_date.day}일 평균기온</div>'
            f'<div style="font-size:40px;font-weight:700;line-height:1.2;color:{ABN_TXT[kind_m]};">{mtd_txt}</div>'
            f'<div style="font-size:15px;font-weight:700;color:{ABN_TXT[kind_m]};">{ABN_LABEL[kind_m]}</div>'
            f'<div style="font-size:12px;color:#777;">{m_norm_txt}</div></div>'
        )
        st.markdown(kpi_card("월간 누적 달성률", rate_mtd, f"{int(a_mtd):,} GJ", a_mtd - p_mtd,
                             f"누적 계획: {int(p_mtd):,} GJ", ABN_BG[kind_m], m_html), unsafe_allow_html=True)

    with col_g3:
        mask_ytd = (df['날짜'].dt.year == target_date.year) & (df['날짜'] <= target_date)
        ytd_data = df[mask_ytd]
        a_ytd, p_ytd = ytd_data['실적(GJ)'].sum(), ytd_data['계획(GJ)'].sum()
        rate_ytd = (a_ytd/p_ytd*100) if p_ytd > 0 else 0
        st.markdown(kpi_card("연간 누적 달성률", rate_ytd, f"{int(a_ytd):,} GJ", a_ytd - p_ytd,
                             f"누적 계획: {int(p_ytd):,} GJ"), unsafe_allow_html=True)

    # ── 계획 대비 증감 원인(기온 효과) 설명 박스 ──
    _hist_for_model = load_historical_data_common()
    heat_model = None
    if _hist_for_model is not None and not _hist_for_model.empty:
        _h = _hist_for_model.dropna(subset=["평균기온(℃)", "val_gj"])
        heat_model = build_heat_model(_h["평균기온(℃)"].to_numpy(float), (_h["val_gj"] * 1000.0).to_numpy(float))
    st.markdown("<br>", unsafe_allow_html=True)
    render_temp_effect_box(heat_model, ts_abn, target_date, day_temp, current_val_gj, plan_val_gj)

    # ── 설명 박스 바로 아래: 1도 변화에 따른 공급량 변화 (기본: 숨김) ──
    if st.toggle("1도 변화에 따른 공급량 변화", value=False, key="show_sens"):
        if heat_model is None:
            st.info("기온–공급량 관계를 계산할 과거 자료가 부족합니다.")
        else:
            _h2 = _hist_for_model.dropna(subset=["평균기온(℃)", "val_gj"])
            st.subheader("🧊 B. Heating Start / Slowdown — 수요곡선")
            st.plotly_chart(build_heat_fig_demand(heat_model, _h2["평균기온(℃)"].to_numpy(float),
                                                  (_h2["val_gj"] * 1000.0).to_numpy(float)),
                            use_container_width=True, config={"displaylogo": False, "scrollZoom": True})
            st.subheader("🌡️ C. 기온별 공급량 변화량 요약")
            cv = HEAT_MJ_PER_M3
            rows_c = [("Total Avg @ " + f"{heat_model['mean_temp']:.1f}℃",
                       heat_band_mean(heat_model, heat_model["mean_temp"], heat_model["mean_temp"])),
                      ("−5~0℃", heat_band_mean(heat_model, -5, 0)),
                      ("0~5℃", heat_band_mean(heat_model, 0, 5)),
                      ("5~10℃", heat_band_mean(heat_model, 5, 10)),
                      ("10~15℃", heat_band_mean(heat_model, 10, 15))]
            md = f"**Polynomial Regression (degree 3)** **{heat_model['eq']}**\n\n"
            for nm, v in rows_c:
                md += f"- **Supply ↑ per −1°C ({nm})** : **{v:,.0f} MJ/℃, {v / cv:,.0f} Nm³/℃** (단위열량 {cv:.3f} MJ/Nm³ 적용)\n"
            st.markdown(md)
            st.caption(f"R²={heat_model['r2']:.3f} · 구글시트 일별 실적 전체 기간 기준")


    # ── [열량 실적 하단] 이상기온 판별 상세 ──
    st.markdown("<br>", unsafe_allow_html=True)
    render_abnormal_section(stat_m, target_date.month, same_win, target_date.day)

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
        # [수정] 아직 오지 않은 날(미래 일자)·미입력 일자는 엑셀에서 공급량=0, 평균기온=0으로 채워져 있어
        # 0~5℃ 구간에 '공급량 0'으로 섞여 들어가 평균을 끌어내리므로 실적이 있는 날만 사용
        sub = sub[sub[act_col] > 0]
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
        # 그래프 우측 상단: 당해연도 기온 표시 버튼 (우측 축 ℃)
        try:
            _pt, _p1, _p2 = st.columns([5, 1.1, 1.1], vertical_alignment="center")
        except TypeError:
            _pt, _p1, _p2 = st.columns([5, 1.1, 1.1])
        with _pt:
            st.markdown(f"**{sel_year}년 {sel_month}월 일별 공급량 패턴**")
        with _p1:
            show_tavg = st.toggle("평균기온", value=False, key=f"{key_prefix}pat_tavg",
                                  help=f"{sel_year}년 {sel_month}월 일평균기온을 우측 축(℃)에 표시합니다.")
        with _p2:
            show_tmin = st.toggle("최저기온", value=False, key=f"{key_prefix}pat_tmin",
                                  help=f"{sel_year}년 {sel_month}월 일 최저기온을 우측 축(℃)에 표시합니다.")

        _C_MAIN, _C_PLAN, _C_PREV = "#1A73E8", "#F5A800", "#8F959C"
        _C_TAVG, _C_TMIN = "#34A853", "#A142F4"
        _pastel = ["#AFC8EE", "#C6BEEB", "#EDB9C6", "#B7D9BE", "#EBD49B", "#B5D3DE", "#D9C3B0"]

        def _rgba_p(h, a):
            h = h.lstrip("#"); return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})"

        fig1 = go.Figure()
        prev_year = sel_year - 1
        # 과거 연도: 연한 얇은 곡선, 전년도는 회색 굵은 곡선
        for idx, y in enumerate(past_years):
            sub = df_all[(df_all["연"] == y) & (df_all["월"] == sel_month)].copy()
            if sub.empty: continue
            is_prev = (y == prev_year)
            fig1.add_scatter(
                x=sub["일"], y=sub[act_col] / 1000.0, mode="lines", name=f"{y}년 실적",
                line=dict(color=_C_PREV if is_prev else _pastel[idx % len(_pastel)],
                          width=2.4 if is_prev else 1.6, shape="spline", smoothing=0.6),
                hovertemplate="%{y:,.0f} GJ<extra>" + f"{y}년</extra>")
        if plan_curve_x:
            fig1.add_scatter(
                x=plan_curve_x, y=plan_curve_y, mode="lines", name=f"{sel_year}년 계획",
                line=dict(color=_C_PLAN, width=2.6, dash="dot", shape="spline", smoothing=0.6),
                hovertemplate="%{y:,.0f} GJ<extra>계획</extra>")
        if not this_df.empty:
            ymin_fill = float(this_df[act_col].min() / 1000.0) * 0.5
            fig1.add_scatter(x=this_df["일"], y=[ymin_fill] * len(this_df), mode="lines",
                             line=dict(width=0), showlegend=False, hoverinfo="skip", name="_base")
            fig1.add_scatter(
                x=this_df["일"], y=this_df[act_col] / 1000.0, mode="lines+markers", name=f"{sel_year}년 실적",
                line=dict(color=_C_MAIN, width=3.6, shape="spline", smoothing=0.6),
                marker=dict(size=8, color=_C_MAIN, line=dict(color="white", width=1.5)),
                fill="tonexty", fillcolor=_rgba_p(_C_MAIN, 0.08),
                hovertemplate="%{y:,.0f} GJ<extra>" + f"{sel_year}년 실적</extra>")

        # 당해연도 기온 (우측 축) — 구글시트의 평균기온/최저기온
        _t_all = [v for v in (show_tavg, show_tmin) if v]
        if _t_all:
            ts_ = load_temperature_sheet()
            tcur = None
            if ts_ is not None and not ts_.empty:
                tcur = ts_[(ts_["연도"] == sel_year) & (ts_["월"] == sel_month)].sort_values("일")
                if last_valid_date is not pd.NaT and pd.notna(last_valid_date):
                    tcur = tcur[tcur["일자"] <= last_valid_date]
            if show_tavg:
                if tcur is not None and tcur["평균기온(℃)"].notna().any():
                    xa, ya = tcur["일"], tcur["평균기온(℃)"]
                else:                                   # 시트에 없으면 실적 데이터의 평균기온으로 대체
                    xa, ya = this_df["일"], this_df["평균기온(℃)"] if "평균기온(℃)" in this_df.columns else []
                fig1.add_scatter(x=xa, y=ya, mode="lines+markers", name=f"{sel_year}년 평균기온(℃)", yaxis="y2",
                                 line=dict(color=_C_TAVG, width=2.4, dash="dot", shape="spline", smoothing=0.8),
                                 marker=dict(size=5, color=_C_TAVG), hovertemplate="%{y:.1f} ℃<extra>평균기온</extra>")
            if show_tmin and tcur is not None and tcur["최저기온(℃)"].notna().any():
                fig1.add_scatter(x=tcur["일"], y=tcur["최저기온(℃)"], mode="lines+markers", name=f"{sel_year}년 최저기온(℃)",
                                 yaxis="y2", line=dict(color=_C_TMIN, width=2.4, dash="dot", shape="spline", smoothing=0.8),
                                 marker=dict(size=5, color=_C_TMIN), hovertemplate="%{y:.1f} ℃<extra>최저기온</extra>")
            elif show_tmin:
                st.caption("※ 구글시트에서 최저기온을 읽지 못했습니다.")

        _ax = "#80868B"; _gr = "rgba(148,163,184,0.20)"
        fig1.update_layout(
            height=470, margin=dict(l=10, r=10, t=50, b=10), plot_bgcolor="white", hovermode="x unified",
            xaxis=dict(title=dict(text="일", font=dict(color=_ax, size=12)), tickfont=dict(color=_ax, size=11),
                       showgrid=False, showline=False, zeroline=False, automargin=True),
            yaxis=dict(automargin=True, title=dict(text="공급량 (GJ)", font=dict(color=_ax, size=12)), tickfont=dict(color=_ax, size=11),
                       gridcolor=_gr, showline=False, zeroline=False, tickformat=","),
            legend=dict(orientation="h", yanchor="bottom", y=1.03, xanchor="right", x=1, font=dict(size=12)),
        )
        if _t_all:
            # 같은 그래프 안에서 공급량은 위쪽, 기온(우측 축)은 아래쪽 띠에 오도록 두 축의 범위를 맞춤
            sup_y = [float(v) for t in fig1.data if getattr(t, "yaxis", None) != "y2" and t.name != "_base"
                     for v in (t.y if t.y is not None else []) if pd.notna(v)]
            tmp_y = [float(v) for t in fig1.data if getattr(t, "yaxis", None) == "y2"
                     for v in (t.y if t.y is not None else []) if pd.notna(v)]
            if sup_y and tmp_y:
                s_lo, s_hi = min(sup_y), max(sup_y)
                t_lo, t_hi = min(tmp_y), max(tmp_y)
                s_w = max((s_hi - s_lo) / 0.65, 1.0); s_rng0 = s_lo - 0.33 * s_w          # 공급량: 위쪽 약 65%
                t_w = max((t_hi - t_lo) / 0.25, 1.0); t_rng0 = t_lo - 0.02 * t_w          # 기온: 바로 아래 약 25%
                for t in fig1.data:
                    if t.name == "_base":
                        t.y = [s_lo - 0.05 * (s_hi - s_lo)] * len(t.y)
                import math
                s_step = 10000 if (s_hi - s_lo) > 40000 else 5000
                s_ticks = list(range(int(math.ceil(s_lo / s_step)) * s_step, int(s_hi) + 1, s_step))
                t_step = 2 if (t_hi - t_lo) <= 14 else 5
                t_ticks = list(range(int(math.floor(t_lo / t_step)) * t_step, int(math.ceil(t_hi)) + 1, t_step))
                fig1.update_layout(
                    height=740,
                    yaxis=dict(range=[s_rng0, s_rng0 + s_w], tickmode="array", tickvals=s_ticks),
                    yaxis2=dict(title=dict(text="기온 (℃)", font=dict(color=_ax, size=12)), overlaying="y", side="right",
                                range=[t_rng0, t_rng0 + t_w], tickmode="array", tickvals=t_ticks, showgrid=False,
                                showline=False, zeroline=False, automargin=True, tickfont=dict(color=_ax, size=11)))
                fig1.add_hline(y=s_rng0 + 0.29 * s_w, line_dash="dot", line_color="rgba(100,116,139,0.35)", line_width=1)  # 공급량/기온 구분선
        st.plotly_chart(fig1, use_container_width=True)

        # ─────────────────────────────────────────────
        # 📊 [NEW] 연도별 월 누적 공급량 · 평균기온 비교
        # ─────────────────────────────────────────────
        cmp_years = sorted(set(past_years + [sel_year]))
        cutoff_day = int(this_df["일"].max()) if not this_df.empty else 31

        # 제목(좌) + 옵션 토글(우측 상단)
        hd_title, hd_opt1, hd_opt2, hd_opt3, hd_opt4 = st.columns([2.6, 1.5, 0.9, 1.3, 1.0])
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
        with hd_opt4:
            show_exp = st.toggle("예상 실적", value=False, key=f"{key_prefix}cum_exp",
                                 help="마지막 실적일 이후 남은 기간은 일일계획량을 그대로 더해, 월간 계획 대비 예상 달성률을 보여줍니다.")

        period_txt = f"1~{cutoff_day}일" if (use_cutoff and not show_exp) else "월말까지(월 전체)"
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
            if use_cutoff and not show_exp:   # 예상 실적(월말 기준)을 켜면 월 전체로 비교
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

            # 예상 실적: 마지막 실적일까지 실적 + 남은 기간 일일계획량 = 당월 말일 예상
            plan_stat = None   # 계획 대비 통계(항상 계산) / exp_info는 '예상 실적' 토글이 켜졌을 때만 사용
            if f"{sel_year}년" in cum_df["연도"].values:
                pm = None
                if plan_df is not None and not this_df.empty:
                    pm = plan_df[(plan_df["날짜"].dt.year == sel_year) & (plan_df["날짜"].dt.month == sel_month)]
                if pm is None or pm.empty:
                    if show_exp:
                        st.info(f"{sel_year}년 {sel_month}월 계획 데이터가 없어 예상 실적을 계산할 수 없습니다.")
                else:
                    last_act = this_df["일자"].max()
                    act_gj = float(this_df[act_col].sum() / 1000.0)
                    plan_month_gj = float(pm["plan_gj"].sum())
                    plan_to_date = float(pm.loc[pm["날짜"] <= last_act, "plan_gj"].sum())
                    rem = pm[pm["날짜"] > last_act]
                    rem_gj = float(rem["plan_gj"].sum())
                    plan_stat = dict(
                        act=act_gj, rem=rem_gj, exp=act_gj + rem_gj, plan_month=plan_month_gj,
                        rate=(act_gj + rem_gj) / plan_month_gj * 100 if plan_month_gj > 0 else 0.0,
                        cur_rate=act_gj / plan_to_date * 100 if plan_to_date > 0 else 0.0,
                        last_day=int(last_act.day),
                        rem_txt=(f"{int(rem['날짜'].dt.day.min())}~{int(rem['날짜'].dt.day.max())}일 ({len(rem)}일)"
                                 if not rem.empty else "남은 기간 없음"),
                    )
            exp_info = plan_stat if show_exp else None
            top_val = max(float(cum_df["누적공급량(GJ)"].max()), exp_info["exp"] if exp_info else 0.0)

            if show_min and cum_df["최저기온(℃)"].isna().all():
                st.warning("최저기온 데이터를 가져오지 못했습니다. (구글시트 '최저' 열과 기상청 API 모두 값이 없음)")

            # 팔레트: 과거=라이트 그레이(#BEBEBE), 기준연도=블루(#005AC8), 평균기온=앰버, 최저기온=틸, 가정용 청구전수=스카이 블루
            C_PAST, C_SEL, C_AVG, C_MIN, C_TXT = "#D8DBE0", "#2563EB", "#F5A800", "#34A853", "#5F6368"   # C_SEL: 기준연도 로열 블루
            C_AVG_TXT, C_MIN_TXT = "#B97A00", "#1E7B3A"          # 기온 라벨 글자색(회색 막대 위)
            C_AVG_TXT_SEL, C_MIN_TXT_SEL = "#FFE9A8", "#C8F0D3"  # 기준연도(진한 파랑 막대) 위에서는 밝은 글자색
            C_HH, C_HH_TXT = "#A142F4", "#7A2FC0"
            sel_label = f"{sel_year}년"
            bar_colors = [C_SEL if c == sel_label else C_PAST for c in cum_df["연도"]]

            # ── 세로 배치(보조축 범위 조정) ──
            # 기온선은 '가장 짧은 막대의 상단보다 아래'(막대 몸통 안쪽)에 두어 막대 상단 숫자와 겹치지 않게 하고,
            # 평균기온/최저기온은 각각 따로 눈금을 잡아 위아래 폭이 크게 보이도록 함
            # 가정용 청구전수를 켜면 막대 위쪽에 선이 들어갈 여백을 더 확보
            y1_max = top_val * (1.3 if show_hh else 1.15)

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
            # 사업계획 월 평균기온은 2026년 계획에만 해당 → 2026년 막대에만 표시
            plan_temp = None
            plan_idx = None
            if sel_label in cum_df["연도"].values and sel_year == 2026:
                plan_temp = PLAN_TEMP_2026.get(int(sel_month))
                plan_idx = cum_df["연도"].tolist().index(sel_label)
            if plan_temp is not None:                        # 점선이 축 범위 밖으로 나가지 않도록 범위 계산에 포함
                avg_vals = pd.concat([avg_vals, pd.Series([float(plan_temp)])], ignore_index=True)
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
                    bar_top_max = top_val / y1_max
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
                        text=[
                            ("" if (exp_info and c == sel_label)
                             else (f"{v:,.0f}<br><b>계획대비 {plan_stat['cur_rate']:.1f}%</b>" if (plan_stat and c == sel_label)
                                   else f"{v:,.0f}"))
                            for c, v in zip(cum_df["연도"], cum_df["누적공급량(GJ)"])
                        ],
                        textposition="outside",
                        textfont=dict(color=C_TXT, size=12),
                        hovertemplate="%{x}<br>누적: %{y:,.0f} GJ<extra></extra>",
                    ),
                    secondary_y=False,
                )

                if exp_info:   # 남은 기간 계획량을 실적 막대 위에 이어 붙여 당월 말일 예상 실적을 표시
                    fig_cum.add_trace(
                        go.Bar(
                            x=[sel_label], y=[exp_info["rem"]], base=[exp_info["act"]], name="예상(남은 기간 계획)",
                            marker=dict(color="rgba(37,99,235,0.22)", line=dict(color=C_SEL, width=1.5),
                                        pattern=dict(shape="/", fgcolor=C_SEL, size=6)),
                            text=[f"<b>예상 {exp_info['exp']:,.0f}</b><br>계획대비 {exp_info['rate']:.1f}%"],
                            textposition="outside", textfont=dict(color=C_SEL, size=16),   # 12 → 16 (약 30% 확대)
                            hovertemplate=(f"{sel_label} 예상<br>실적 {exp_info['act']:,.0f} + 계획 {exp_info['rem']:,.0f}"
                                           f" = {exp_info['exp']:,.0f} GJ<extra></extra>"),
                        ),
                        secondary_y=False,
                    )

                def add_temp_line(col, name, color, txt_color, txt_color_sel, dash, symbol, axis):
                    # 흰색 바탕선(케이싱)을 먼저 깔아 막대 위에서도 선이 또렷하게 보이도록 함
                    fig_cum.add_trace(
                        go.Scatter(
                            x=cum_df["연도"], y=cum_df[col], mode="lines", yaxis=axis,
                            line=dict(color="rgba(255,255,255,0.9)", width=7, shape="spline", smoothing=0.8),
                            hoverinfo="skip", showlegend=False,
                        )
                    )
                    # 기준연도(진한 파랑 막대) 위의 라벨만 밝은 글자색으로 표시
                    label_colors = [txt_color_sel if c == sel_label else txt_color for c in cum_df["연도"]]
                    fig_cum.add_trace(
                        go.Scatter(
                            x=cum_df["연도"], y=cum_df[col], name=f"{name}(℃)",
                            mode="lines+markers+text", yaxis=axis,
                            line=dict(color=color, width=3.2, dash=dash, shape="spline", smoothing=0.8),
                            marker=dict(size=9, symbol=symbol, color=color, line=dict(color="white", width=2)),
                            text=cum_df[col].map(lambda v: f"<b>{v:.1f}℃</b>" if pd.notna(v) else ""),
                            textposition="top center",   # 모든 점의 라벨을 점 바로 위 가운데 정렬
                            textfont=dict(color=label_colors, size=12),
                            hovertemplate="%{x}<br>" + name + ": %{y:.1f}℃<extra></extra>",
                        )
                    )

                # 평균기온=보조축(y2), 최저기온=별도 축(y4), 가정용 청구전수=별도 축(y3) — 모두 눈금은 숨김
                add_temp_line("평균기온(℃)", "평균기온", C_AVG, C_AVG_TXT, C_AVG_TXT_SEL, "solid", "circle", "y2")
                # 2026 사업계획 월 평균기온: 2026년 막대에만 빨간 점선 + 온도 표기 (평균기온선과 같은 보조축 y2)
                if plan_temp is not None:
                    # 도형은 항상 그래프 선 위에 그려지므로, 평균기온 점·라벨이 있는 가운데(±0.17)는 비우고
                    # 좌·우 두 토막으로 그려서 현재 평균기온이 가려지지 않게 함
                    for _x0, _x1 in ((plan_idx - 0.45, plan_idx - 0.17), (plan_idx + 0.17, plan_idx + 0.45)):
                        fig_cum.add_shape(
                            type="line", xref="x", yref="y2",
                            x0=_x0, x1=_x1, y0=float(plan_temp), y1=float(plan_temp),
                            line=dict(color="#D93025", width=3, dash="dot"), layer="above",
                        )
                    fig_cum.add_annotation(
                        xref="x", yref="y2", x=plan_idx + 0.48, y=float(plan_temp), xanchor="left", yanchor="middle",
                        text=f"<b>계획 {plan_temp:.1f}℃</b>", showarrow=False,
                        font=dict(color="#D93025", size=13),
                    )
                if show_min and min_range is not None:
                    add_temp_line("최저기온(℃)", "최저기온", C_MIN, C_MIN_TXT, C_MIN_TXT_SEL, "dot", "diamond", "y4")
                if show_hh and hh_range is not None:
                    fig_cum.add_trace(
                        go.Scatter(
                            x=cum_df["연도"], y=cum_df["가정용 청구전수"], name="가정용 청구전수",
                            mode="lines+markers+text", yaxis="y3",
                            line=dict(color=C_HH, width=2.8, dash="dash", shape="spline", smoothing=0.8),
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
                    margin=dict(l=10, r=10, t=50, b=20),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=12)),
                    bargap=0.45,
                    plot_bgcolor="white",
                    font=dict(size=12, color=C_TXT),
                )
                fig_cum.update_xaxes(showgrid=False, showline=False, tickfont=dict(color="#80868B", size=12))
                fig_cum.update_yaxes(
                    title_text="누적 공급량 (GJ)", secondary_y=False,
                    range=[0, y1_max],
                    gridcolor="rgba(148,163,184,0.20)", zeroline=False, showline=False,
                    tickfont=dict(color="#80868B", size=11), title_font=dict(color="#80868B", size=12)
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
                if exp_info:
                    fig_cum.update_layout(barmode="overlay")
                if plan_temp is not None:   # 점선 오른쪽에 계획 기온 라벨이 들어갈 여백 확보
                    fig_cum.update_xaxes(range=[-0.5, len(cum_df) - 0.5 + 0.9])
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

                # ── 예상 실적 요약 (실적 + 남은 기간 계획 = 월간 계획 대비 %) ──
                if exp_info:
                    e = exp_info
                    color = "#1A73E8" if e["rate"] >= 100 else "#D93025"
                    st.markdown(f"""<div style="background:#F0F2F6;border-radius:10px;padding:14px 18px;margin-top:8px;">
                        <div style="font-size:15px;color:#555;margin-bottom:6px;">🔮 <b>{sel_year}년 {sel_month}월 예상 실적</b> (남은 기간은 계획량 100% 가정)</div>
                        <div style="font-size:15px;line-height:1.7;">
                        실적 1~{e['last_day']}일: <b>{e['act']:,.0f} GJ</b> (해당 기간 계획 대비 {e['cur_rate']:.1f}%)<br>
                        + 남은 계획 {e['rem_txt']}: <b>{e['rem']:,.0f} GJ</b><br>
                        = 예상 월 공급량 <b>{e['exp']:,.0f} GJ</b> / 월간 계획 <b>{e['plan_month']:,.0f} GJ</b><br>
                        ➡️ 월간 계획 대비 <span style="font-size:24px;font-weight:800;color:{color};">{e['rate']:.1f}%</span>
                        <span style="color:#666;">({e['exp'] - e['plan_month']:+,.0f} GJ)</span>
                        </div></div>""", unsafe_allow_html=True)
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
# [탭 3] 약정물량 (비밀번호 보호) — 약정물량 엑셀의 월별 총량을 과거 10년 월별 실적과 비교
# ==============================================================================
CONTRACT_PW = "1234"


def _contract_pw_gate() -> bool:
    """비밀번호가 맞으면 True. (비밀번호는 코드에 들어 있으므로 코드를 볼 수 있는 사람에겐 노출됩니다)"""
    if st.session_state.get("contract_pw_ok"):
        return True
    st.title("🔒 약정물량")
    with st.form("contract_pw_form"):
        pw = st.text_input("비밀번호", type="password")
        ok = st.form_submit_button("확인")
    if ok:
        if pw == CONTRACT_PW:
            st.session_state["contract_pw_ok"] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    return False


def parse_contract_excel(file_bytes: bytes):
    """약정물량 엑셀('작성양식' 시트)에서 업종별·월별 표와 합계(월별 총량)를 읽는다. 단위: 천N㎥"""
    try:
        xls = pd.ExcelFile(io.BytesIO(file_bytes), engine="openpyxl")
        sheet = "작성양식" if "작성양식" in xls.sheet_names else xls.sheet_names[0]
        raw = xls.parse(sheet, header=None)
    except Exception:
        return None

    def norm(v):
        return "" if pd.isna(v) else str(v).replace(" ", "").replace(" ", "").strip()

    hdr = None
    for i in range(len(raw)):
        vals = [norm(v) for v in raw.iloc[i].values]
        if "1월" in vals and "12월" in vals:
            hdr = i
            break
    if hdr is None:
        return None
    month_col = {}
    for j, v in enumerate(raw.iloc[hdr].values):
        m = re.match(r"^(\d{1,2})월$", norm(v))
        if m and 1 <= int(m.group(1)) <= 12:
            month_col[int(m.group(1))] = j
    if len(month_col) < 12:
        return None
    label_col = min(month_col.values()) - 1

    rows = {}
    for i in range(hdr + 1, len(raw)):
        label = norm(raw.iat[i, label_col]) if label_col >= 0 else ""
        if not label or label.startswith("*"):
            continue
        vals = [pd.to_numeric(raw.iat[i, month_col[m]], errors="coerce") for m in range(1, 13)]
        if pd.Series(vals).notna().sum() == 0:
            continue
        rows[label] = vals
    if not rows:
        return None

    # '수정'(수정본) 행은 업종 행이 아니므로 따로 분리
    rev_key = next((k for k in rows if "수정" in k), None)
    revised_vals = rows.pop(rev_key) if rev_key else None
    detail = pd.DataFrame(rows, index=range(1, 13)).T
    total_key = next((k for k in rows if k == "합계"), None)
    total = detail.loc[total_key] if total_key else detail.sum()
    detail_only = detail.drop(index=total_key) if total_key else detail
    revised = None
    if revised_vals is not None:
        revised = pd.Series(revised_vals, index=range(1, 13), dtype=float)
        revised = revised.fillna(pd.Series(total.values, index=range(1, 13), dtype=float))   # 빈 칸은 원본 값 사용

    year, company = None, ""
    for i in range(min(hdr, 8)):
        for v in raw.iloc[i].values:
            t = "" if pd.isna(v) else str(v)
            m = re.search(r"(\d{4})\s*년도?", t)
            if m and year is None:
                year = int(m.group(1))
            if "회사명" in t:
                company = t.split(":")[-1].strip()
    return dict(total=total.astype(float), detail=detail_only, year=year, company=company, sheet=sheet, revised=revised)


@st.cache_data(show_spinner=False, ttl=600)
def load_monthly_m3_history():
    """연·월별 공급량 합계(천m³). 해당 월의 모든 일자 자료가 있는 달만 사용(진행 중인 달은 NaN). 반환: (연×월 DataFrame, 출처)"""
    h = load_historical_data_common()
    src = "구글시트"
    if h is None or h.empty or float(h["val_m3"].sum()) <= 0:
        # 대체: 같은 폴더의 분석 엑셀 '일별실적' 시트의 공급량(M3)
        h, src = None, "엑셀(대체)"
        try:
            p = Path(__file__).parent / "공급량(계획_실적).xlsx"
            if p.exists():
                d = pd.read_excel(p, sheet_name="일별실적")
                d.columns = [str(c).replace(" ", "") for c in d.columns]
                c_m3 = next((c for c in d.columns if "공급량" in c and "M3" in c.upper()), None)
                if c_m3 and "일자" in d.columns:
                    h = pd.DataFrame({"일자": pd.to_datetime(d["일자"], errors="coerce"),
                                      "val_m3": pd.to_numeric(d[c_m3], errors="coerce")}).dropna()
        except Exception:
            h = None
    if h is None or h.empty:
        return None, None
    h = h.drop_duplicates("일자")
    h = h[h["val_m3"] > 0].copy()
    h["연"], h["월"] = h["일자"].dt.year, h["일자"].dt.month
    g = h.groupby(["연", "월"]).agg(m3=("val_m3", "sum"), n=("val_m3", "size")).reset_index()
    g["dim"] = [pd.Period(year=int(y), month=int(m), freq="M").days_in_month for y, m in zip(g["연"], g["월"])]
    g = g[g["n"] >= g["dim"]]
    piv = (g.pivot(index="연", columns="월", values="m3") / 1000.0).reindex(columns=range(1, 13))
    return piv, src


def build_contract_figure(contract: pd.Series, hist: pd.DataFrame, mx: pd.Series, mn: pd.Series, out_mask: pd.Series,
                          label: str, revised: Optional[pd.Series] = None, rev_out: Optional[pd.Series] = None) -> go.Figure:
    months = [f"{m}월" for m in range(1, 13)]
    fig = go.Figure()
    # 과거 연도별 꺾은선 (얇은 파스텔)
    pastel = ["#AFC8EE", "#C6BEEB", "#EDB9C6", "#B7D9BE", "#EBD49B", "#B5D3DE", "#D9C3B0", "#C9D6A3", "#E3B7DB", "#B9C4CF"]
    for i, (y, row) in enumerate(hist.iterrows()):
        fig.add_trace(go.Scatter(x=months, y=row.values, mode="lines", name=f"{int(y)}년",
                                 line=dict(color=pastel[i % len(pastel)], width=1.6, shape="spline", smoothing=0.5),
                                 hovertemplate="%{y:,.0f} 천㎥<extra>" + f"{int(y)}년</extra>"))
    # 최대/최소 범위 (음영)
    fig.add_trace(go.Scatter(x=months, y=mn.values, mode="lines", name="10년 최소",
                             line=dict(color="#2563EB", width=2, dash="dash", shape="spline", smoothing=0.5),
                             hovertemplate="%{y:,.0f} 천㎥<extra>10년 최소</extra>"))
    fig.add_trace(go.Scatter(x=months, y=mx.values, mode="lines", name="10년 최대",
                             line=dict(color="#D93025", width=2, dash="dash", shape="spline", smoothing=0.5),
                             fill="tonexty", fillcolor="rgba(148,163,184,0.15)",
                             hovertemplate="%{y:,.0f} 천㎥<extra>10년 최대</extra>"))
    # 약정물량
    fig.add_trace(go.Scatter(x=months, y=contract.values, mode="lines+markers+text", name=label,
                             line=dict(color="#111827", width=3.6, shape="spline", smoothing=0.5),
                             marker=dict(size=9, color="#111827", line=dict(color="white", width=2)),
                             text=[f"{v:,.0f}" for v in contract.values], textposition="top center",
                             textfont=dict(size=11, color="#111827"),
                             hovertemplate="%{y:,.0f} 천㎥<extra>" + label + "</extra>"))
    if revised is not None:   # 수정본(엑셀 '수정' 행): 주황 실선
        fig.add_trace(go.Scatter(x=months, y=revised.values, mode="lines+markers+text", name="수정본",
                                 line=dict(color="#F5A800", width=3.6, shape="spline", smoothing=0.5),
                                 marker=dict(size=9, color="#F5A800", line=dict(color="white", width=2)),
                                 text=[f"{v:,.0f}" for v in revised.values], textposition="bottom center",
                                 textfont=dict(size=11, color="#B97A00"),
                                 hovertemplate="%{y:,.0f} 천㎥<extra>수정본</extra>"))
        if rev_out is not None and rev_out.any():
            fig.add_trace(go.Scatter(x=[months[m - 1] for m in rev_out.index[rev_out]], y=revised[rev_out].values,
                                     mode="markers", name="수정본 범위 이탈",
                                     marker=dict(size=16, symbol="x", color="#B71C1C", line=dict(width=3, color="#B71C1C")),
                                     hoverinfo="skip"))
    if out_mask.any():
        fig.add_trace(go.Scatter(x=[months[m - 1] for m in out_mask.index[out_mask]], y=contract[out_mask].values,
                                 mode="markers", name="범위 이탈",
                                 marker=dict(size=16, symbol="x", color="#D93025", line=dict(width=3, color="#D93025")),
                                 hoverinfo="skip"))
    fig.update_layout(height=560, plot_bgcolor="white", hovermode="x unified", margin=dict(l=10, r=10, t=50, b=10),
                      xaxis=dict(showgrid=False, showline=False, tickfont=dict(color="#80868B", size=12)),
                      yaxis=dict(title=dict(text="월별 총량 (천㎥)", font=dict(color="#80868B", size=12)), tickformat=",",
                                 gridcolor="rgba(148,163,184,0.20)", zeroline=False, showline=False,
                                 tickfont=dict(color="#80868B", size=11)),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=12)))
    return fig


SUPPLY_GJ_SHEET_ID = "1gIhArPlLBJ9fwlaqXtZWxiKlSK9hbRuz6HcDw_Yf7Is"   # 상품별 공급량 재분배 (수급량 GJ)
HEAT_MJ_PER_M3 = 42.563   # 열량(MJ/m³): 수급량(GJ) ÷ 42.563 = 천m³


@st.cache_data(show_spinner=False, ttl=600)
def load_monthly_supply_gj_history():
    """ver2: 구글시트 '상품별 공급량 재분배'의 1행(수급량, GJ; D열~)을 6행의 'YYYY-MM' 헤더와 짝지어
    월별 수급량을 읽고, 열량 42.563으로 천m³로 환산. 반환: 연×월 DataFrame(천m³) 또는 None"""
    url = f"https://docs.google.com/spreadsheets/d/{SUPPLY_GJ_SHEET_ID}/export?format=csv&gid=0"
    try:
        raw = pd.read_csv(url, header=None, dtype=str)
    except Exception:
        return None
    # 'YYYY-MM' 형태 헤더가 가장 많은 행 = 월 헤더 행 (기본 6행)
    hdr_row, best = None, 0
    for i in range(min(len(raw), 20)):
        n = sum(bool(re.match(r"^\s*\d{4}\D+\d{1,2}\s*$", str(v))) for v in raw.iloc[i].values)
        if n > best:
            hdr_row, best = i, n
    if hdr_row is None or best < 12:
        return None
    # 수급량(GJ) 값 행: C열에 '수급량'이 적힌 행 (기본 1행)
    val_row = next((i for i in range(min(len(raw), 10)) if "수급량" in str(raw.iat[i, 2]) and "(GJ)" in str(raw.iat[i, 2]).replace(" ", "")), 0) \
        if raw.shape[1] > 2 else 0
    recs = {}
    for j in range(3, raw.shape[1]):       # D열 ~ 끝
        m = re.match(r"^\s*(\d{4})\D+(\d{1,2})\s*$", str(raw.iat[hdr_row, j]))
        v = pd.to_numeric(str(raw.iat[val_row, j]).replace(",", ""), errors="coerce")
        if m and pd.notna(v) and v > 0:
            recs[(int(m.group(1)), int(m.group(2)))] = float(v) / HEAT_MJ_PER_M3   # GJ → 천m³
    if not recs:
        return None
    ser = pd.Series(recs)
    piv = ser.unstack(level=1).reindex(columns=range(1, 13))
    return piv


def _render_contract_version(key: str, piv: pd.DataFrame, src: str, cd: dict, label: str):
    """한 가지 과거 기준(piv: 연×월, 천m³)에 대해 슬라이더·판정·그래프·표를 그리고, 다운로드용 표를 반환"""
    full_years = [int(y) for y in piv.index if piv.loc[y].notna().all()]   # 12개월 모두 완결된 연도만
    if len(full_years) < 2:
        st.error("12개월이 모두 집계된 과거 연도가 부족합니다.")
        return None
    y_max, y_min = max(full_years), min(full_years)
    c1, c2 = st.columns([2, 3])
    with c1:
        yr_range = st.slider("과거 연도 범위", min_value=y_min, max_value=y_max,
                             value=(max(y_min, y_max - 9), y_max), step=1, key=f"{key}_yr_range")
    sel_years = [y for y in full_years if yr_range[0] <= y <= yr_range[1]]
    hist = piv.loc[sel_years]
    contract = cd["total"].copy()
    contract.index = range(1, 13)

    mx, mn, avg = hist.max(), hist.min(), hist.mean()
    over = contract > mx
    under = contract < mn
    out_mask = over | under

    revised = cd.get("revised")
    rev_over = rev_under = rev_out = None
    if revised is not None:
        revised = revised.copy()
        revised.index = range(1, 13)
        rev_over, rev_under = revised > mx, revised < mn
        rev_out = rev_over | rev_under

    with c2:
        st.markdown(f"<div style='padding-top:28px;font-size:14px;color:#666;'>"
                    f"{cd['company'] or ''} · {label} (단위: 천N㎥) vs 과거 {len(sel_years)}개 연도 "
                    f"({sel_years[0]}~{sel_years[-1]}년) 실적(천m³) · 출처: {src}</div>", unsafe_allow_html=True)

    def _verdict(name, o_mask, o_over):
        if o_mask.any():
            bad = ", ".join(f"{m}월({'초과' if o_over[m] else '미달'})" for m in o_mask.index[o_mask])
            st.error(f"🚨 {name}: 과거 {len(sel_years)}년 최대·최소 범위를 벗어난 월이 있습니다: {bad}")
        else:
            st.success(f"✅ {name}: 1~12월이 모두 과거 {len(sel_years)}년 최대·최소 범위 안에 있습니다.")

    _verdict("원본", out_mask, over)
    if revised is not None:
        _verdict("수정본", rev_out, rev_over)

    st.plotly_chart(build_contract_figure(contract, hist, mx, mn, out_mask, label, revised, rev_out),
                    use_container_width=True,
                    key=f"{key}_chart")

    cmp_df = pd.DataFrame({
        "월": [f"{m}월" for m in range(1, 13)],
        f"{label}(천㎥)": contract.values,
        "과거 최소(천㎥)": mn.values, "과거 평균(천㎥)": avg.values, "과거 최대(천㎥)": mx.values,
        "판정": ["최대 초과" if over[m] else ("최소 미달" if under[m] else "범위 내") for m in range(1, 13)],
        "벗어난 양(천㎥)": [(contract[m] - mx[m]) if over[m] else ((contract[m] - mn[m]) if under[m] else 0.0)
                        for m in range(1, 13)],
        "평균 대비(%)": ((contract / avg - 1) * 100).values,
    })
    tot = {"월": "합계", f"{label}(천㎥)": contract.sum(), "과거 최소(천㎥)": mn.sum(),
           "과거 평균(천㎥)": avg.sum(), "과거 최대(천㎥)": mx.sum(), "판정": "", "벗어난 양(천㎥)": np.nan,
           "평균 대비(%)": (contract.sum() / avg.sum() - 1) * 100}
    if revised is not None:   # 수정본 열 추가 (원본 옆에)
        pos = list(cmp_df.columns).index("벗어난 양(천㎥)") + 1
        cmp_df.insert(pos, "수정본(천㎥)", revised.values)
        cmp_df.insert(pos + 1, "수정본 판정",
                      ["최대 초과" if rev_over[m] else ("최소 미달" if rev_under[m] else "범위 내") for m in range(1, 13)])
        cmp_df.insert(pos + 2, "수정-원본(천㎥)", (revised - contract).values)
        tot.update({"수정본(천㎥)": revised.sum(), "수정본 판정": "", "수정-원본(천㎥)": (revised - contract).sum()})
    show_df = pd.concat([cmp_df, pd.DataFrame([tot])], ignore_index=True)

    def _hl(row):
        if row["판정"] in ("최대 초과", "최소 미달") or row.get("수정본 판정") in ("최대 초과", "최소 미달"):
            return ["background-color: #FFD6D6; font-weight: bold"] * len(row)
        if row["월"] == "합계":
            return ["background-color: #F0F2F6; font-weight: bold"] * len(row)
        return [""] * len(row)

    num_cols = [c for c in show_df.columns if "천㎥" in c]
    st.dataframe(
        show_df.style.apply(_hl, axis=1).format({**{c: "{:,.0f}" for c in num_cols}, "평균 대비(%)": "{:+.1f}%"}, na_rep="-")
               .set_properties(**{"text-align": "center"})
               .set_table_styles([dict(selector="th", props=[("text-align", "center")])]),
        use_container_width=True, hide_index=True)

    with st.expander("과거 연도별 월별 총량(천m³) 보기"):
        hist_show = hist.copy()
        hist_show.index = [f"{int(y)}년" for y in hist_show.index]
        hist_show.columns = [f"{m}월" for m in range(1, 13)]
        st.dataframe(hist_show.style.format("{:,.0f}"), use_container_width=True)
    h2 = hist.copy()
    h2.index.name = "연도"
    h2.columns = [f"{m}월" for m in range(1, 13)]
    return dict(cmp=cmp_df, hist=h2.reset_index())


def run_tab3_contract():
    if not _contract_pw_gate():
        return

    st.sidebar.header("📂 [약정물량] 데이터 파일")
    up = st.sidebar.file_uploader("약정물량 엑셀 업로드", type=["xlsx"], key="u3")
    file_bytes = None
    if up is not None:
        file_bytes = up.getvalue()
        st.sidebar.success("✅ 약정물량 파일 로드 성공")
    else:   # 업로드가 없으면 앱 폴더의 '약정' 엑셀을 찾아 사용
        cands = sorted(Path(__file__).parent.glob("*약정*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
        if cands:
            file_bytes = cands[0].read_bytes()
            st.sidebar.info(f"ℹ️ 기본 약정물량 파일 사용 ({cands[0].name})")

    st.title("📑 약정물량 분석")
    if file_bytes is None:
        st.info("👈 좌측 사이드바에서 약정물량 엑셀 파일을 업로드해주세요.")
        return
    cd = parse_contract_excel(file_bytes)
    if cd is None:
        st.error("약정물량 엑셀에서 '1월~12월' 표를 찾지 못했습니다. (작성양식 시트의 월별 표 형식을 확인하세요)")
        return

    label = f"{cd['year']}년 약정물량" if cd["year"] else "약정물량"
    # ── ver2: 수급량(GJ) ÷ 42.563 = 천m³ ──
    st.header(f"수급량 기준 (수급량 GJ ÷ {HEAT_MJ_PER_M3} → 천m³)")
    piv2 = load_monthly_supply_gj_history()
    res2 = None
    if piv2 is None or piv2.empty:
        st.error("수급량 시트(상품별 공급량 재분배)를 읽지 못했습니다. 시트 공유가 '링크가 있는 모든 사용자 보기'인지, "
                 "1행(수급량 GJ)·6행(YYYY-MM) 위치가 맞는지 확인해주세요.")
    else:
        res2 = _render_contract_version("contract_v2", piv2, "구글시트 상품별 공급량 재분배 1행 ÷ 42.563", cd, label)
    st.caption("※ 약정은 천N㎥, 과거 실적은 천m³이며 동일 단위로 간주했습니다. 해당 월·연이 모두 집계된 연도만 포함합니다.")

    with st.expander("업종별 약정물량(천N㎥) 보기"):
        det = cd["detail"].copy()
        det.columns = [f"{m}월" for m in range(1, 13)]
        det["소계"] = det.sum(axis=1)
        st.dataframe(det.style.format("{:,.0f}"), use_container_width=True)

    # 엑셀 다운로드: ver1 / ver2 비교표·과거 월별 총량 + 업종별 약정물량
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        if res2:
            res2["cmp"].to_excel(writer, sheet_name="약정vs과거범위", index=False)
            res2["hist"].to_excel(writer, sheet_name="과거월별총량(천m3)", index=False)
        d2 = cd["detail"].copy()
        d2.columns = [f"{m}월" for m in range(1, 13)]
        d2.index.name = "업종"
        d2.reset_index().to_excel(writer, sheet_name="업종별약정물량(천Nm3)", index=False)
    st.download_button("💾 약정물량 분석 데이터 엑셀 저장", buf.getvalue(),
                       f"약정물량_분석_{cd['year'] or ''}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ==============================================================================
# [메인 실행] 사이드바 네비게이션
# ==============================================================================
st.sidebar.title("통합 메뉴")
menu = st.sidebar.radio("이동", ["1. 도시가스 공급실적 관리", "2. 공급량 분석", "3. 약정물량"])

if menu == "1. 도시가스 공급실적 관리":
    run_tab1_management()
elif menu == "2. 공급량 분석":
    run_tab2_analysis()
else:
    run_tab3_contract()
