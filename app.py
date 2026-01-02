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
# [공통] 데이터 로드 및 정제 함수
# ─────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_repo_file():
    """레포지토리의 기본 파일(공급량(계획_실적).xlsx)을 로드"""
    path = Path(__file__).parent / "공급량(계획_실적).xlsx"
    if path.exists():
        return path
    return None

def process_repo_data_for_tab1(file_path):
    """
    Tab 2용 파일(월별/일별 시트)을 읽어서 Tab 1용 포맷(일별 계획/실적 합본)으로 변환
    """
    try:
        xls = pd.ExcelFile(file_path, engine="openpyxl")
        
        # 1. 일별 실적 로드
        sheet_d = next((s for s in xls.sheet_names if "일별" in s), None)
        df_d = pd.read_excel(xls, sheet_name=sheet_d) if sheet_d else pd.DataFrame()
        
        # 2. 월별 계획 로드
        sheet_m = next((s for s in xls.sheet_names if "월별" in s), None)
        df_m = pd.read_excel(xls, sheet_name=sheet_m) if sheet_m else pd.DataFrame()

        # 3. 데이터 가공
        if df_d.empty: return None

        # 컬럼 공백 제거
        df_d.columns = [str(c).replace(" ", "").strip() for c in df_d.columns]
        df_m.columns = [str(c).replace(" ", "").strip() for c in df_m.columns]

        # 일별 데이터 정리
        col_date = next((c for c in df_d.columns if "일자" in c or "date" in c.lower()), None)
        col_mj_act = next((c for c in df_d.columns if "공급량" in c and "MJ" in c), None)
        col_m3_act = next((c for c in df_d.columns if "공급량" in c and "M3" in c), None)

        if not col_date: return None

        df_d = df_d.rename(columns={col_date: '날짜'})
        df_d['날짜'] = pd.to_datetime(df_d['날짜'], errors='coerce')
        df_d = df_d.dropna(subset=['날짜'])
        
        # 실적(MJ -> GJ 변환)
        if col_mj_act:
            df_d['실적(GJ)'] = (pd.to_numeric(df_d[col_mj_act], errors='coerce').fillna(0) / 1000).round(0)
        else:
            df_d['실적(GJ)'] = 0
            
        if col_m3_act:
            df_d['실적(m3)'] = pd.to_numeric(df_d[col_m3_act], errors='coerce').fillna(0)
        else:
            df_d['실적(m3)'] = 0

        # 월별 계획을 일별로 배분 (단순 배분)
        # 월별 시트에서 연, 월, 계획MJ 컬럼 찾기
        col_y = next((c for c in df_m.columns if "연" in c), None)
        col_m = next((c for c in df_m.columns if "월" in c), None)
        col_mj_plan = next((c for c in df_m.columns if "계획" in c and "MJ" in c), None) # 첫번째 계획 컬럼 사용

        plan_map = {}
        if col_y and col_m and col_mj_plan:
            for _, row in df_m.iterrows():
                try:
                    y, m = int(row[col_y]), int(row[col_m])
                    plan_val = float(row[col_mj_plan])
                    if pd.notna(plan_val):
                        # 해당 월의 일수 계산
                        days_in_month = pd.Timestamp(y, m, 1).days_in_month
                        daily_plan_gj = (plan_val / 1000 / days_in_month)
                        plan_map[(y, m)] = daily_plan_gj
                except:
                    continue

        # 일별 데이터에 계획 매핑
        df_d['계획(GJ)'] = df_d.apply(lambda r: plan_map.get((r['날짜'].year, r['날짜'].month), 0), axis=1).round(0)
        df_d['계획(m3)'] = 0 # m3 계획은 복잡하므로 일단 0

        return df_d[['날짜', '계획(GJ)', '실적(GJ)', '계획(m3)', '실적(m3)']]

    except Exception:
        return None

# ─────────────────────────────────────────────────────────
# [탭 1] 도시가스 공급실적 관리
# ─────────────────────────────────────────────────────────
def run_tab1_management():
    # --- 1. 데이터 로드 ---
    if 'data_tab1' not in st.session_state:
        st.session_state.data_tab1 = None

    st.sidebar.header("📂 [관리] 데이터 파일")
    uploaded = st.sidebar.file_uploader("관리용 엑셀 업로드", type=['xlsx'], key="u1")
    
    # 1순위: 업로드 파일
    if uploaded:
        try:
            # 업로드된 파일이 '연간' 시트 포맷인지, '공급량(계획_실적)' 포맷인지 확인 필요
            # 여기서는 편의상 공급량 포맷으로 처리 시도 후 실패하면 연간 포맷 시도
            df = process_repo_data_for_tab1(uploaded)
            if df is None:
                # 기존 방식 (연간 시트) 시도
                raw = pd.read_excel(uploaded, sheet_name='연간', header=None)
                # (기존 로딩 로직 생략 - 필요시 복원 가능, 지금은 통합 위주)
                # 간단하게 처리
                pass 
            
            if df is not None:
                st.session_state.data_tab1 = df
                st.sidebar.success("✅ 파일 로드 성공")
        except:
            st.sidebar.error("파일 로드 실패")

    # 2순위: 기본 파일 (공급량(계획_실적).xlsx)
    elif st.session_state.data_tab1 is None:
        repo_file = load_repo_file()
        if repo_file:
            df = process_repo_data_for_tab1(repo_file)
            if df is not None:
                st.session_state.data_tab1 = df
                st.sidebar.info(f"ℹ️ 기본 파일 사용 (공급량(계획_실적).xlsx)")
            else:
                st.sidebar.warning("기본 파일 형식 변환 실패")
        else:
            st.sidebar.warning("기본 파일이 없습니다.")

    if st.session_state.data_tab1 is None:
        st.warning("👈 좌측 사이드바에서 엑셀 파일을 업로드해주세요.")
        return

    df = st.session_state.data_tab1

    st.title("🔥 도시가스 공급실적 관리")

    # --- 2. 날짜 선택 ---
    col_date, col_space = st.columns([1, 5])
    with col_date:
        # 데이터가 있는 가장 최신 날짜 찾기
        valid_dates = df[df['실적(GJ)'] > 0]['날짜']
        default_date = valid_dates.max() if not valid_dates.empty else df['날짜'].min()
        selected_date = st.date_input("조회 기준일", value=default_date, label_visibility="collapsed")
    target_date = pd.to_datetime(selected_date)

    # --- 3. 랭킹 계산 (Tab 2 데이터와 비교) ---
    def get_historical_ranks(current_val, target_dt):
        repo_file = load_repo_file()
        if not repo_file: return None
        try:
            # 원본 데이터 로드 (전체 과거 데이터)
            df_hist = process_repo_data_for_tab1(repo_file)
            if df_hist is None: return None
            
            # 자기 자신(오늘 날짜) 제외
            df_hist = df_hist[df_hist['날짜'] != target_dt]
            
            # 0보다 큰 값만
            vals_all = df_hist[df_hist['실적(GJ)'] > 0]['실적(GJ)']
            
            # 전체 랭킹
            rank_all = (vals_all > current_val).sum() + 1
            
            # 동월 랭킹
            vals_month = df_hist[(df_hist['날짜'].dt.month == target_dt.month) & (df_hist['실적(GJ)'] > 0)]['실적(GJ)']
            rank_month = (vals_month > current_val).sum() + 1
            
            firecracker = "🎉" if rank_all == 1 else ""
            return f"{firecracker} 🏆 역대 전체: {int(rank_all)}위  /  📅 역대 {target_dt.month}월: {int(rank_month)}위"
        except:
            return None

    # --- 4. KPI 계산 ---
    mask_day = df['날짜'] == target_date
    if not mask_day.any():
        # 데이터 없으면 행 추가
        new_row = pd.DataFrame({'날짜': [target_date], '계획(GJ)': [0], '실적(GJ)': [0], '계획(m3)': [0], '실적(m3)': [0]})
        df = pd.concat([df, new_row], ignore_index=True)
        st.session_state.data_tab1 = df
    
    curr_row = df.loc[df['날짜'] == target_date].iloc[0]
    curr_gj = float(curr_row['실적(GJ)'])
    plan_gj = float(curr_row['계획(GJ)'])
    
    # 랭킹 텍스트
    rank_text = ""
    if curr_gj > 0:
        rt = get_historical_ranks(curr_gj, target_date)
        if rt: rank_text = rt

    # --- 5. 화면 표시 ---
    st.markdown("### 🔥 열량 실적 (GJ)")
    col_g1, col_g2, col_g3 = st.columns(3)
    
    # 누적 계산
    mask_mtd = (df['날짜'] <= target_date) & (df['날짜'].dt.month == target_date.month) & (df['날짜'].dt.year == target_date.year)
    mask_ytd = (df['날짜'] <= target_date) & (df['날짜'].dt.year == target_date.year)
    
    with col_g1:
        rate = (curr_gj / plan_gj * 100) if plan_gj > 0 else 0
        st.metric(label=f"일간 달성률 {rate:.1f}%", value=f"{int(curr_gj):,} GJ", delta=f"{int(curr_gj - plan_gj):+,} GJ")
        st.caption(f"계획: {int(plan_gj):,} GJ")
        if rank_text: st.info(rank_text)

    with col_g2:
        d_mtd = df[mask_mtd]
        a_mtd = d_mtd['실적(GJ)'].sum()
        p_mtd = d_mtd['계획(GJ)'].sum()
        rate_mtd = (a_mtd / p_mtd * 100) if p_mtd > 0 else 0
        st.metric(label=f"월간 누적 달성률 {rate_mtd:.1f}%", value=f"{int(a_mtd):,} GJ", delta=f"{int(a_mtd - p_mtd):+,} GJ")
        st.caption(f"누적 계획: {int(p_mtd):,} GJ")

    with col_g3:
        d_ytd = df[mask_ytd]
        a_ytd = d_ytd['실적(GJ)'].sum()
        p_ytd = d_ytd['계획(GJ)'].sum()
        rate_ytd = (a_ytd / p_ytd * 100) if p_ytd > 0 else 0
        st.metric(label=f"연간 누적 달성률 {rate_ytd:.1f}%", value=f"{int(a_ytd):,} GJ", delta=f"{int(a_ytd - p_ytd):+,} GJ")
        st.caption(f"누적 계획: {int(p_ytd):,} GJ")

    st.markdown("---")
    st.markdown("### 💧 부피 실적 (천 m³)")
    # (부피 부분은 형님 코드 유지 - 간단하게 표시)
    curr_m3 = float(curr_row['실적(m3)']) / 1000
    plan_m3 = float(curr_row['계획(m3)']) / 1000
    col_m1, col_m2, col_m3 = st.columns(3)
    with col_m1:
        st.metric(label="일간 실적", value=f"{int(curr_m3):,} (천 m³)", delta=f"{int(curr_m3 - plan_m3):+,}")
    with col_m2:
        a_mtd_m3 = df[mask_mtd]['실적(m3)'].sum() / 1000
        st.metric(label="월간 누적", value=f"{int(a_mtd_m3):,} (천 m³)")
    with col_m3:
        a_ytd_m3 = df[mask_ytd]['실적(m3)'].sum() / 1000
        st.metric(label="연간 누적", value=f"{int(a_ytd_m3):,} (천 m³)")

    st.markdown("---")
    st.subheader(f"📝 {target_date.month}월 실적 입력")
    st.info("💡 값을 수정하고 엔터(Enter)를 치면 상단 그래프와 랭킹이 즉시 업데이트됩니다.")

    # --- 6. 에디터 ---
    mask_month_view = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month)
    view_df = df.loc[mask_month_view].copy()

    st.markdown("##### 1️⃣ 열량(GJ) 입력")
    edited_gj = st.data_editor(
        view_df[['날짜', '계획(GJ)', '실적(GJ)']],
        column_config={
            "날짜": st.column_config.DateColumn("공급일자", format="YYYY-MM-DD", disabled=True),
            "계획(GJ)": st.column_config.NumberColumn("계획(GJ)", format="%d", disabled=True),
            "실적(GJ)": st.column_config.NumberColumn("실적(GJ) ✏️", format="%d", min_value=0),
        },
        hide_index=True, use_container_width=True, key="editor_gj"
    )

    if not edited_gj.equals(view_df[['날짜', '계획(GJ)', '실적(GJ)']]):
        df.update(edited_gj)
        st.session_state.data_tab1 = df
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("##### 2️⃣ 부피(천 m³) 입력")
    view_m3 = view_df[['날짜', '계획(m3)', '실적(m3)']].copy()
    # 표시용으로 천 단위 변환
    view_m3['계획(천m3)'] = (view_m3['계획(m3)'] / 1000).round(0).astype(int)
    view_m3['실적(천m3)'] = (view_m3['실적(m3)'] / 1000).round(0).astype(int)

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
        new_vals = edited_m3['실적(천m3)'] * 1000
        df.loc[mask_month_view, '실적(m3)'] = new_vals.values
        st.session_state.data_tab1 = df
        st.rerun()
        
    st.markdown("---")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='연간', index=False)
    st.download_button("💾 관리 데이터 엑셀 저장", buffer, f"실적데이터_{target_date.strftime('%Y%m%d')}.xlsx")


# ==============================================================================
# [탭 2] 공급량 분석 (형님이 주신 코드 그대로 유지 + 인덴트/오류 수정)
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
        # 이 함수는 Tab 2 내부에서 2026 계획 데이터를 가져오기 위한 것
        # Tab 1에서 수정된 데이터가 있으면 그걸 우선할 수 있도록 아래 main 로직에서 처리함
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
        except:
            return None

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
        for c in ["공급량(MJ)", "공급량(M3)", "평균기온(℃)"]:
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
        with c1: 
            sel_year = st.selectbox("기준 연도", years_all, index=years_all.index(default_year), key=f"{key_prefix}year")
        with c2: 
            sel_month = st.selectbox("기준 월", list(range(1, 13)), index=0, key=f"{key_prefix}month") 
        with c3: 
            st.markdown(f"<div style='padding-top:28px;font-size:14px;color:#666;'>집계 기준: <b>당월(일별)</b></div>", unsafe_allow_html=True)
        
        st.markdown(f"<div style='margin-top:-4px;font-size:13px;color:#666;'>선택 기준: <b>{sel_year}년 {sel_month}월</b></div>", unsafe_allow_html=True)
        return sel_year, sel_month, years_all

    def _render_supply_top_card(rank, row, icon, gradient):
        date_str = f"{int(row['연'])}년 {int(row['월'])}월 {int(row['일'])}일"
        supply_str = f"{row['공급량_GJ']:,.1f} GJ"
        temp_str = f"{row['평균기온(℃)']:.1f}℃" if not pd.isna(row["평균기온(℃)"]) else "-"
        
        html = f"""<div style="border-radius:20px;padding:16px 20px;background:{gradient};box-shadow:0 4px 14px rgba(0,0,0,0.06);margin-top:8px;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;"><div style="font-size:26px;">{icon}</div><div style="font-size:15px;font-weight:700;">최대 공급량 기록 {rank}위</div></div>
        <div style="font-size:14px;margin-bottom:3px;">📅 <b>{date_str}</b></div>
        <div style="font-size:14px;margin-bottom:3px;">🔥 공급량: <b>{supply_str}</b></div>
        <div style="font-size:14px;margin-bottom:6px;">🌡 평균기온: <b>{temp_str}</b></div>
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
        fig.update_layout(height=520, margin=dict(l=10, r=10, t=30, b=10), coloraxis_colorbar=dict(title="°C"))
        st.plotly_chart(fig, use_container_width=True)
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
        
        # [데이터 통합] Tab 1에서 입력된 최신 데이터 병합 (중요)
        if 'data_tab1' in st.session_state and st.session_state.data_tab1 is not None:
            new_data = st.session_state.data_tab1.copy()
            # 실적 있는 것만 가져옴
            new_data = new_data[new_data['실적(GJ)'] > 0][['날짜', '실적(GJ)']].copy()
            new_data.columns = ['일자', act_col]
            new_data[act_col] = new_data[act_col] * 1000 # GJ -> MJ로 변환
            
            # 병합
            day_df = pd.concat([day_df, new_data]).drop_duplicates(subset=['일자'], keep='last').sort_values('일자')
            day_df["연"] = day_df["일자"].dt.year
            day_df["월"] = day_df["일자"].dt.month
            day_df["일"] = day_df["일자"].dt.day

        # 데이터 정리
        df_all = day_df.copy()
        this_df = df_all[(df_all["연"] == sel_year) & (df_all["월"] == sel_month)].copy()
        
        # 2026 일별 계획 데이터 로드
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
        
        # (1) 2026년 실제 계획
        if plan_curve_x:
            fig1.add_scatter(x=plan_curve_x, y=plan_curve_y, mode="lines", name=f"{sel_year}년 {sel_month}월 계획 (사업계획)", line=dict(color="#FF4B4B", width=3, dash="dot"), hovertemplate="%{y:,.0f} GJ<extra></extra>")

        # (2) 과거 연도 실적
        pastel_colors = ["#93C5FD", "#A5B4FC", "#C4B5FD", "#FDA4AF", "#FCA5A5", "#FCD34D", "#86EFAC"]
        prev_year = sel_year - 1

        for idx, y in enumerate(past_years):
            sub = df_all[(df_all["연"] == y) & (df_all["월"] == sel_month)].copy()
            if sub.empty: continue
            line_color = "#3B82F6" if y == prev_year else pastel_colors[idx % len(pastel_colors)]
            line_width = 3 if y == prev_year else 1.5
            op_mode = "lines+markers" if y == prev_year else "lines"
            fig1.add_scatter(x=sub["일"], y=sub[act_col] / 1000.0, mode=op_mode, name=f"{y}년 {sel_month}월 실적", line=dict(color=line_color, width=line_width), hovertemplate="%{y:,.0f} GJ<extra></extra>")
            
        # (3) 당년도 실적 (입력된 데이터 포함)
        if not this_df.empty: 
            fig1.add_scatter(x=this_df["일"], y=this_df[act_col] / 1000.0, mode="lines+markers", name=f"{sel_year}년 {sel_month}월 실적", line=dict(color="black", width=4), hovertemplate="%{y:,.0f} GJ<extra></extra>")
        
        fig1.update_layout(title=f"{sel_year}년 {sel_month}월 일별 공급량 패턴", xaxis_title="일", yaxis_title="공급량 (GJ)", margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig1, use_container_width=True)

        # 4. 편차 그래프
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

        # 5. Top 랭킹
        st.markdown("---")
        st.markdown("### 💎 일별 공급량 Top 랭킹")
        month_all = df_all[df_all["월"] == sel_month].copy()
        if not month_all.empty:
            top_n = st.slider("표시할 순위 개수", 5, 50, 10, 5, key=f"{key_prefix}top_n")
            
            # [Highlight Card]
            st.markdown(f"#### 📅 {sel_month}월 기준 Top 랭킹")
            if not this_df.empty:
                max_row = this_df.loc[this_df[act_col].idxmax()]
                max_val_gj = max_row[act_col] / 1000.0
                all_vals_gj = df_all[act_col] / 1000.0
                rank_total = (all_vals_gj > max_val_gj).sum() + 1
                month_vals_gj = month_all[act_col] / 1000.0
                rank_month = (month_vals_gj > max_val_gj).sum() + 1
                target_date_str = f"{int(max_row['연'])}년 {int(max_row['월'])}월 {int(max_row['일'])}일"
                st.markdown(f"""<div style="background-color:#e0f2fe;padding:15px;border-radius:10px;border:1px solid #bae6fd;margin-bottom:20px;">
                    <h4 style="margin:0; color:#0369a1;">📢 {sel_year}년 {sel_month}월 최고 실적 분석 ({target_date_str})</h4>
                    <div style="font-size:16px; margin-top:5px; color:#333;">공급량: <b>{max_val_gj:,.1f} GJ</b> ➡️ <span style="background-color:#fff; padding:2px 8px; border-radius:5px; border:1px solid #ddd; margin-left:5px;">🏆 역대 전체 <b>{rank_total}위</b></span> <span style="background-color:#fff; padding:2px 8px; border-radius:5px; border:1px solid #ddd; margin-left:5px;">📅 역대 {sel_month}월 중 <b>{rank_month}위</b></span></div></div>""", unsafe_allow_html=True)

            month_all["공급량_GJ"] = month_all[act_col] / 1000.0
            rank_df = month_all.sort_values("공급량_GJ", ascending=False).head(top_n).copy()
            rank_df.insert(0, "Rank", range(1, len(rank_df) + 1))
            
            st.dataframe(center_style(rank_df[["Rank", "공급량_GJ", "연", "월", "일", "평균기온(℃)"]].style.format({"공급량_GJ": "{:,.1f}", "평균기온(℃)": "{:,.1f}"})), use_container_width=True, hide_index=True)

            st.markdown("---")
            st.markdown("#### 🏆 전체 기간 Top 랭킹")
            global_top = df_all.sort_values(act_col, ascending=False).head(top_n).copy()
            global_top["공급량_GJ"] = global_top[act_col] / 1000.0
            global_top.insert(0, "Rank", range(1, len(global_top) + 1))
            st.dataframe(center_style(global_top[["Rank", "공급량_GJ", "연", "월", "일", "평균기온(℃)"]].style.format({"공급량_GJ": "{:,.1f}", "평균기온(℃)": "{:,.1f}"})), use_container_width=True, hide_index=True)

            # 3차 다항식
            st.markdown("#### 🌡️ 기온별 공급량 변화 (3차 다항식)")
            temp_supply = month_all.dropna(subset=["평균기온(℃)", act_col]).copy()
            temp_supply = temp_supply[temp_supply[act_col] > 100]

            if len(temp_supply) > 4:
                x = temp_supply["평균기온(℃)"].values
                y = temp_supply[act_col].values / 1000.0
                coeffs = np.polyfit(x, y, 3)
                p = np.poly1d(coeffs)
                xs = np.linspace(x.min() - 1, x.max() + 1, 150)
                
                fig3 = go.Figure()
                fig3.add_scatter(x=x, y=y, mode="markers", name="일별 데이터", marker=dict(size=7, opacity=0.7))
                fig3.add_scatter(x=xs, y=p(xs), mode="lines", name="3차 다항 회귀", line=dict(color="#FF4B4B", width=2))
                fig3.update_layout(title=f"{sel_month}월 기온별 공급량", xaxis_title="기온(℃)", yaxis_title="공급량 (GJ)", margin=dict(l=10, r=10, t=40, b=10))
                st.plotly_chart(fig3, use_container_width=True)

        st.markdown("---")
        temperature_matrix(day_df, sel_month, key_prefix + "temp_")
        temperature_supply_band_section(day_df, sel_month, key_prefix + "band_")

    st.sidebar.header("📂 [분석] 데이터 파일")
    st.sidebar.info("기본적으로 '공급량(계획_실적).xlsx' 파일을 사용합니다.")
    
    # 파일 업로드 (분석용)
    uploaded_analysis = st.sidebar.file_uploader("분석용 엑셀 업로드 (선택)", type=['xlsx'], key="u2")
    
    supply_bytes = None
    if uploaded_analysis:
        supply_bytes = uploaded_analysis.getvalue()
        st.sidebar.success("✅ 분석 파일 로드 성공")
    else:
        # 기본 파일 로드
        repo_file = load_repo_file()
        if repo_file:
            supply_bytes = repo_file.read_bytes()

    st.title("📊 도시가스 공급량 분석 (일별)")

    if supply_bytes:
        month_df, day_df = load_supply_sheets(supply_bytes)
        month_df = clean_supply_month_df(month_df)
        day_df = clean_supply_day_df(day_df)

        if month_df.empty or day_df.empty:
            st.error("데이터 로드 실패: 시트가 없거나 비어있습니다.")
        else:
            act_col = "실적_공급량(MJ)"
            long_dummy = month_df[["연", "월"]].copy()
            long_dummy["계획/실적"] = "실적"
            
            # 값 변환 안전하게 처리
            if act_col in month_df.columns:
                long_dummy["값"] = pd.to_numeric(month_df[act_col], errors="coerce")
            else:
                long_dummy["값"] = 0
            
            long_dummy = long_dummy.dropna(subset=["값"])
            sel_year, sel_month, years_all = render_section_selector_daily(long_dummy, "공급량(일) 기준 선택", "supplyD_base_")
            st.markdown("---")
            supply_daily_main_logic(day_df, month_df, sel_year, sel_month, key_prefix="supplyD_")
    else:
        st.info("데이터 파일이 없습니다.")


# ==============================================================================
# [메인 실행] 사이드바 네비게이션
# ==============================================================================
st.sidebar.title("통합 메뉴")
menu = st.sidebar.radio("이동", ["1. 도시가스 공급실적 관리", "2. 공급량 분석"])

if menu == "1. 도시가스 공급실적 관리":
    run_tab1_management()
else:
    run_tab2_analysis()
