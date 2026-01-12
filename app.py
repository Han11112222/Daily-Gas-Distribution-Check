import streamlit as st
import pandas as pd
import numpy as np
import io
import matplotlib as mpl
import plotly.express as px
import plotly.graph_objects as go
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

# ─────────────────────────────────────────────────────────
# [공통 함수 1] 실적 데이터 로드
# ─────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_historical_data_common():
    path = Path(__file__).parent / "공급량(계획_실적).xlsx"
    if not path.exists(): return None
    try:
        xls = pd.ExcelFile(path, engine="openpyxl")
        sheet_name = "일별실적" if "일별실적" in xls.sheet_names else xls.sheet_names[0]
        df = pd.read_excel(xls, sheet_name=sheet_name)
        df.columns = [str(c).replace(" ", "").strip() for c in df.columns]
        
        col_date = next((c for c in df.columns if "일자" in c or "date" in c.lower()), None)
        col_mj = next((c for c in df.columns if "실적" in c and ("MJ" in c or "GJ" in c)), None)
        if not col_mj:
             col_mj = next((c for c in df.columns if "공급량" in c and ("MJ" in c or "GJ" in c)), None)
        col_m3 = next((c for c in df.columns if ("실적" in c or "공급량" in c) and ("M3" in c or "m3" in c)), None)
        
        if not col_date or not col_mj: return None
        
        df[col_date] = pd.to_datetime(df[col_date], errors='coerce')
        df = df.dropna(subset=[col_date])
        
        df['val_gj'] = pd.to_numeric(df[col_mj], errors='coerce').fillna(0)
        if "MJ" in col_mj.upper():
           df['val_gj'] = df['val_gj'] / 1000.0
           
        if col_m3:
           df['val_m3'] = pd.to_numeric(df[col_m3], errors='coerce').fillna(0)
        else:
           df['val_m3'] = 0
           
        df = df[df['val_gj'] > 0].copy()
        
        if "평균기온(℃)" in df.columns:
             df["평균기온(℃)"] = pd.to_numeric(df["평균기온(℃)"], errors='coerce')
        else:
             df["평균기온(℃)"] = np.nan

        return df[['val_gj', 'val_m3', col_date, '평균기온(℃)']].rename(columns={col_date: '일자'})
    except: return None

# ─────────────────────────────────────────────────────────
# [공통 함수 2] 2026년 계획 데이터 로드
# ─────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_2026_plan_data_common():
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
            elif ('계획' in c or '예상' in c) and ('GJ' in c or 'MJ' in c): col_map['p_gj'] = c
            elif ('계획' in c or '예상' in c) and ('m3' in c or 'M3' in c): col_map['p_m3'] = c

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


# ==============================================================================
# [탭 1] 도시가스 공급실적 관리 (수정됨: 랭킹 설명 문구 크기 및 색상 변경)
# ==============================================================================
def run_tab1_management():
    if 'tab1_df' not in st.session_state:
        df_hist = load_historical_data_common()
        if df_hist is not None and not df_hist.empty:
            init_df = df_hist.rename(columns={
                '일자': '날짜',
                'val_gj': '실적(GJ)',
                'val_m3': '실적(m3)'
            })
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
    uploaded = st.sidebar.file_uploader("연간계획 엑셀 업로드", type=['xlsx'], key="u1")
    
    st.title("🔥 도시가스 공급실적 관리")

    col_date, _ = st.columns([1, 4])
    with col_date:
        max_date = df[df['실적(GJ)'] > 0]['날짜'].max()
        if pd.isna(max_date): max_date = pd.to_datetime("2026-01-01")
        selected_date = st.date_input("조회 기준일", value=max_date)
    target_date = pd.to_datetime(selected_date)

    mask_day = df['날짜'] == target_date
    current_row = df[mask_day]
    
    if current_row.empty:
        p_gj, p_m3 = 0, 0
        if df_plan_file is not None:
            p_row = df_plan_file[df_plan_file['날짜'] == target_date]
            if not p_row.empty:
                p_gj = p_row['plan_gj'].iloc[0]
                p_m3 = p_row['plan_m3'].iloc[0]

        new_row = pd.DataFrame([{
            '날짜': target_date,
            '계획(GJ)': p_gj,
            '실적(GJ)': 0,
            '계획(m3)': p_m3,
            '실적(m3)': 0,
            '평균기온(℃)': np.nan
        }])
        df = pd.concat([df, new_row], ignore_index=True)
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
            # [수정됨] 글자 크기 150%, 색상 검정(black)으로 변경
            st.markdown(
                f"<span style='font-size: 150%; color: red; font-weight: bold;'>{rank_text}</span>"
                f"<br>"
                f"<span style='font-size: 150%; color: black;'>(2014년 1월 1일 이후 랭킹)</span>", 
                unsafe_allow_html=True
            )
            
            if is_top_rank:
                st.balloons()
                st.toast("🎉 축하합니다! 역대 최고 공급량(1위)을 달성했습니다! 🎆")

    with col_g2:
        mask_mtd = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month) & (df['날짜'] <= target_date)
        mtd_data = df[mask_mtd]
        a_mtd = mtd_data['실적(GJ)'].sum()
        p_mtd = mtd_data['계획(GJ)'].sum()
        rate_mtd = (a_mtd/p_mtd*100) if p_mtd > 0 else 0
        st.metric(label=f"월간 누적 달성률 {rate_mtd:.1f}%", value=f"{int(a_mtd):,} GJ", delta=f"{int(a_mtd-p_mtd):+,} GJ")
        st.caption(f"누적 계획: {int(p_mtd):,} GJ")

    with col_g3:
        mask_ytd = (df['날짜'].dt.year == target_date.year) & (df['날짜'] <= target_date)
        ytd_data = df[mask_ytd]
        a_ytd = ytd_data['실적(GJ)'].sum()
        p_ytd = ytd_data['계획(GJ)'].sum()
        rate_ytd = (a_ytd/p_ytd*100) if p_ytd > 0 else 0
        st.metric(label=f"연간 누적 달성률 {rate_ytd:.1f}%", value=f"{int(a_ytd):,} GJ", delta=f"{int(a_ytd-p_ytd):+,} GJ")
        st.caption(f"누적 계획: {int(p_ytd):,} GJ")

    st.markdown("---")
    st.markdown("### 💧 부피 실적 (천 m³)")
    col_m1, col_m2, col_m3 = st.columns(3)
    d_m3 = current_val_m3 / 1000 if current_val_m3 > 10000 else current_val_m3
    p_m3 = plan_val_m3 / 1000 if plan_val_m3 > 10000 else plan_val_m3
    
    with col_m1:
        st.metric(label="일간 실적", value=f"{int(d_m3):,} (천 m³)", delta=f"{int(d_m3 - p_m3):+,}")
        st.caption(f"계획: {int(p_m3):,}")
    with col_m2:
        a_mtd_m3 = mtd_data['실적(m3)'].sum()
        d_mtd_m3 = a_mtd_m3 / 1000 if a_mtd_m3 > 10000 else a_mtd_m3
        st.metric(label="월간 누적", value=f"{int(d_mtd_m3):,} (천 m³)")
    with col_m3:
        a_ytd_m3 = ytd_data['실적(m3)'].sum()
        d_ytd_m3 = a_ytd_m3 / 1000 if a_ytd_m3 > 10000 else a_ytd_m3
        st.metric(label="연간 누적", value=f"{int(d_ytd_m3):,} (천 m³)")

    st.markdown("---")
    st.subheader(f"📝 {target_date.month}월 실적 입력")
    st.info("💡 값을 수정하고 엔터(Enter)를 치면 상단 그래프와 랭킹이 즉시 업데이트됩니다.")

    mask_month_view = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month)
    view_df = df.loc[mask_month_view].copy()
    
    st.markdown("##### 1️⃣ 열량(GJ) 및 기온 입력")
    edited_gj = st.data_editor(
        view_df[['날짜', '계획(GJ)', '실적(GJ)', '평균기온(℃)']],
        column_config={
            "날짜": st.column_config.DateColumn("공급일자", format="YYYY-MM-DD", disabled=True),
            "계획(GJ)": st.column_config.NumberColumn("계획(GJ)", format="%d", disabled=True),
            "실적(GJ)": st.column_config.NumberColumn("실적(GJ) ✏️", format="%d", min_value=0),
            "평균기온(℃)": st.column_config.NumberColumn("평균기온(℃) ✏️", format="%.1f", step=0.1),
        },
        hide_index=True, use_container_width=True, key="editor_gj"
    )

    if not edited_gj.equals(view_df[['날짜', '계획(GJ)', '실적(GJ)', '평균기온(℃)']]):
        df.update(edited_gj)
        st.session_state.tab1_df = df
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    
    st.markdown("##### 2️⃣ 부피(천 m³) 입력")
    view_m3 = view_df[['날짜', '계획(m3)', '실적(m3)']].copy()
    view_m3['계획(천m3)'] = view_m3['계획(m3)'].apply(lambda x: int(x/1000) if x > 10000 else int(x))
    view_m3['실적(천m3)'] = view_m3['실적(m3)'].apply(lambda x: int(x/1000) if x > 10000 else int(x))
    
    edited_m3 = st.data_editor(
        view_m3[['날짜', '계획(천m3)', '실적(천m3)']],
        column_config={
            "날짜": st.column_config.DateColumn("공급일자", format="YYYY-MM-DD", disabled=True),
            "계획(천m3)": st.column_config.NumberColumn("계획(천m³)", format="%d", disabled=True),
            "실적(천m3)": st.column_config.NumberColumn("실적(천m³) ✏️", format="%d", min_value=0),
        },
        hide_index=True, use_container_width=True, key="editor_m3"
    )

    if not edited_m3.equals(view_m3[['날짜', '계획(천m3)', '실적(천m3)']]):
        new_plan_m3 = edited_m3['계획(천m3)'] * 1000
        new_act_m3 = edited_m3['실적(천m3)'] * 1000
        df.loc[mask_month_view, '계획(m3)'] = new_plan_m3.values
        df.loc[mask_month_view, '실적(m3)'] = new_act_m3.values
        st.session_state.tab1_df = df
        st.rerun()

    st.markdown("---")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='연간', index=False)
    st.download_button("💾 관리 데이터 엑셀 저장", buffer, f"실적데이터_{target_date.strftime('%Y%m%d')}.xlsx")


# ==============================================================================
# [탭 2] 공급량 분석 (수정 없음)
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
        try:
            path = Path(__file__).parent / "2026_연간_일별공급계획_2.xlsx"
            if not path.exists(): return None
            raw = pd.read_excel(path, sheet_name='연간', header=None)
            header_idx = None
            for i, row in raw.iterrows():
                if '연' in row.astype(str).values and '월' in row.astype(str).values:
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
            df['날짜'] = pd.to_datetime({
                'year': pd.to_numeric(df[col_map['y']], errors='coerce'),
                'month': pd.to_numeric(df[col_map['m']], errors='coerce'),
                'day': pd.to_numeric(df[col_map['d']], errors='coerce')
            }, errors='coerce')
            df['plan_gj'] = pd.to_numeric(df[col_map['p_gj']], errors='coerce').fillna(0)
            return df[['날짜', 'plan_gj']].dropna()
        except: return None

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
        with c2: sel_month = st.selectbox("기준 월", list(range(1, 13)), index=0, key=f"{key_prefix}month") 
        with c3: st.markdown(f"<div style='padding-top:28px;font-size:14px;color:#666;'>집계 기준: <b>당월(일별)</b></div>", unsafe_allow_html=True)
        st.markdown(f"<div style='margin-top:-4px;font-size:13px;color:#666;'>선택 기준: <b>{sel_year}년 {sel_month}월</b></div>", unsafe_allow_html=True)
        return sel_year, sel_month, years_all

    def _render_supply_top_card(rank, row, icon, gradient):
        date_str = f"{int(row['연'])}년 {int(row['월'])}월 {int(row['일'])}일"
        supply_str = f"{row['공급량_GJ']:,.1f} GJ"
        
        # m3 단위 추가 (천m3)
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
        if day_df.empty or "평균기온(℃)" not in day_df.columns: return
        day_df = day_df.copy()
        day_df["연"] = day_df["일자"].dt.year
        day_df["월"] = day_df["일자"].dt.month
        day_df["일"] = day_df["일자"].dt.day
        years = sorted(day_df["연"].unique().tolist())
        if not years: return
        min_y, max_y = years[0], years[-1]
        c1, c2 = st.columns([2, 1.2])
        with c1: yr_range = st.slider("연도 범위", min_value=min_y, max_value=max_y, value=(min_y, max_y), step=1, key=f"{key_prefix}yr_range")
        with c2: sel_m = st.selectbox("월 선택", options=list(range(1, 13)), index=default_month - 1, key=f"{key_prefix}month")
        sub = day_df[(day_df["연"].between(yr_range[0], yr_range[1])) & (day_df["월"] == sel_m)]
        if sub.empty: return
        pivot = sub.pivot_table(index="일", columns="연", values="평균기온(℃)", aggfunc="mean").reindex(range(1, 32))
        avg_row = pivot.mean(axis=0).to_frame().T
        avg_row.index = ["평균"]
        pivot2 = pd.concat([pivot, avg_row], axis=0)
        fig = px.imshow(pivot2, aspect="auto", labels=dict(x="연도", y="일", color="°C"), color_continuous_scale="RdBu_r")
        
        fig.update_layout(
            height=780, 
            margin=dict(l=10, r=10, t=30, b=10), 
            coloraxis_colorbar=dict(title="°C"),
            xaxis=dict(fixedrange=True, title="연도"),
            yaxis=dict(fixedrange=True, title="일"),
            dragmode=False,
            hovermode="closest"
        )
        
        fig.update_traces(
            hovertemplate="<b>%{x}년 " + str(sel_m) + "월 %{y}일</b><br>🌡️ 평균기온: %{z:.1f}℃<extra></extra>"
        )
        
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        
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
        sub["기온구간"] = pd.cut(sub["평균기온(℃)"], bins=bins, labels=labels, right=False)
        grp = sub.groupby("기온구간", as_index=False).agg(평균공급량_GJ=(act_col, lambda x: x.mean() / 1000.0), 일수=(act_col, "count")).dropna(subset=["기온구간"])
        fig = px.bar(grp, x="기온구간", y="평균공급량_GJ", text="일수")
        fig.update_layout(xaxis_title="기온 구간", yaxis_title="평균 공급량 (GJ)", margin=dict(l=10, r=10, t=40, b=10))
        fig.update_traces(texttemplate="%{text}일", textposition="outside")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(center_style(grp.rename(columns={"평균공급량_GJ": "평균공급량(GJ)"}).style.format({"평균공급량(GJ)": "{:,.1f}"})), use_container_width=True, hide_index=True)

    def supply_daily_main_logic(day_df, month_df, sel_year, sel_month, key_prefix):
        st.markdown("## 📅 공급량 분석(일)")
        if day_df.empty or month_df.empty: return
        act_col = "공급량(MJ)"
        if act_col not in day_df.columns: return
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
            plan_month = plan_df[plan_df['날짜'].dt.month == sel_month]
            if not plan_month.empty:
                plan_curve_x = plan_month['날짜'].dt.day.tolist()
                plan_curve_y = plan_month['plan_gj'].tolist()
        st.markdown(f"### 📈 {sel_month}월 일별 패턴 비교")
        cand_years = sorted(df_all["연"].unique().tolist())
        past_candidates = [y for y in cand_years if y < sel_year]
        default_years = past_candidates[-2:] if len(past_candidates) >= 2 else past_candidates
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
        if not this_df.empty and plan_curve_x:
            st.markdown("### 🧮 일일계획 대비 편차")
            plan_sub = pd.DataFrame({'일': plan_curve_x, 'plan_gj': plan_curve_y})
            merged = pd.merge(this_df, plan_sub, on='일', how='left')
            merged['편차_GJ'] = (merged[act_col] / 1000.0) - merged['plan_gj']
            fig2 = go.Figure()
            fig2.add_bar(x=merged["일"], y=merged["편차_GJ"], name="편차", marker_color="#FF4B4B", hovertemplate="%{y:,.0f} GJ<extra></extra>")
            fig2.update_layout(title=f"계획 대비 편차 (실적-계획)", xaxis_title="일", yaxis_title="편차 (GJ)", margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig2, use_container_width=True)
            show = merged[["일자", act_col, "편차_GJ"]].copy()
            show.columns = ["일자", "일별실적(GJ)", "편차(GJ)"]
            show["일별실적(GJ)"] = show["일별실적(GJ)"].apply(lambda v: v / 1000.0)
            st.dataframe(center_style(show.style.format("{:,.1f}", subset=["일별실적(GJ)", "편차(GJ)"])), use_container_width=True, hide_index=True)
        
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
        temperature_supply_band_section(day_df, sel_month, key_prefix + "band_")

    st.sidebar.header("📂 [분석] 데이터 파일")
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
