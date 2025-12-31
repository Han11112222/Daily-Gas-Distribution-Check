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
# [0-1] 사이드바 메뉴 (최상단 배치 요청 반영)
# ─────────────────────────────────────────────────────────
st.sidebar.title("통합 메뉴")
menu = st.sidebar.radio("이동", ["1. 도시가스 공급실적 관리", "2. 공급량 분석"])
st.sidebar.markdown("---") # 구분선

# ─────────────────────────────────────────────────────────
# [공통] 데이터 로더 (강력한 필터링 & 표준화)
# ─────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_history_data(file_content):
    """
    분석용 과거 데이터를 로드하여 전처리하는 함수
    - 컬럼명을 year, month, day, val_gj로 표준화
    - 합계 데이터(300만 GJ 이상) 및 날짜 오류 데이터 제거
    """
    try:
        xls = pd.ExcelFile(io.BytesIO(file_content), engine="openpyxl")
        sheet_name = "월별계획_실적" if "월별계획_실적" in xls.sheet_names else xls.sheet_names[0]
        
        # 헤더 자동 탐색 (1~10행 확인)
        raw = pd.read_excel(xls, sheet_name=sheet_name, header=None, nrows=20)
        header_idx = None
        for i, row in raw.iterrows():
            row_str = row.astype(str).values
            # 연, 월, 실적이라는 단어가 포함된 행을 헤더로 간주
            if any('연' in s or '년' in s for s in row_str) and \
               any('월' in s for s in row_str) and \
               any('실적' in s for s in row_str):
                header_idx = i
                break
        
        # 전체 데이터 로드
        if header_idx is not None:
            df = pd.read_excel(xls, sheet_name=sheet_name, header=header_idx)
        else:
            df = pd.read_excel(xls, sheet_name=sheet_name)

        # 컬럼 매핑 (유연하게 찾기)
        cols = df.columns.astype(str).tolist()
        col_act = next((c for c in cols if '실적' in c and ('GJ' in c or 'MJ' in c)), None)
        col_year = next((c for c in cols if '연' in c or '년' in c), None)
        col_month = next((c for c in cols if '월' in c), None)
        col_day = next((c for c in cols if '일' in c), None)
            
        if not col_act or not col_year or not col_month or not col_day:
            return None

        # 1. 표준 컬럼명으로 변경
        df = df.rename(columns={
            col_year: 'year',
            col_month: 'month',
            col_day: 'day',
            col_act: 'val_origin'
        })

        # 2. 데이터 정제 (숫자 변환)
        for c in ['year', 'month', 'day', 'val_origin']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        
        # NaN 제거 (날짜나 값이 없는 행 삭제)
        df = df.dropna(subset=['year', 'month', 'day', 'val_origin'])
        
        # 3. [핵심] 필터링: 합계 및 이상치 제거
        # 조건 A: '일'이 1~31 정수가 아니면 제거
        df = df[(df['day'] >= 1) & (df['day'] <= 31)]
        
        # 4. 단위 변환 (MJ -> GJ)
        if 'MJ' in col_act:
            df['val_gj'] = df['val_origin'] / 1000.0
        else:
            df['val_gj'] = df['val_origin']
            
        # 조건 B: 일일 공급량이 3,000,000 GJ 이상이면 제거 (월간 합계)
        df = df[df['val_gj'] < 3000000]
        # 조건 C: 0 이하 제거
        df = df[df['val_gj'] > 0]

        # 정수형 변환
        df['year'] = df['year'].astype(int)
        df['month'] = df['month'].astype(int)
        df['day'] = df['day'].astype(int)
        
        return df[['year', 'month', 'day', 'val_gj']]
        
    except Exception as e:
        return None

# 사이드바 파일 업로드 (메뉴 아래에 배치)
st.sidebar.header("📂 [공통] 데이터 파일")
uploaded_history = st.sidebar.file_uploader("과거 실적(History) 업로드", type=['xlsx'], key="u_hist")
uploaded_plan = st.sidebar.file_uploader("2026 연간 계획 업로드", type=['xlsx'], key="u_plan")

# 히스토리 데이터 로드 및 세션 저장
if uploaded_history:
    hist_df = load_history_data(uploaded_history.getvalue())
    if hist_df is not None and not hist_df.empty:
        st.session_state['history_df'] = hist_df
        st.sidebar.success(f"✅ 과거 데이터 {len(hist_df):,}건 로드")
    else:
        st.sidebar.error("❌ 과거 데이터 로드 실패")
else:
    # 기본 파일 로드
    try:
        default_hist_path = Path(__file__).parent / "공급량(계획_실적).xlsx"
        if default_hist_path.exists() and 'history_df' not in st.session_state:
            hist_df = load_history_data(default_hist_path.read_bytes())
            if hist_df is not None: 
                st.session_state['history_df'] = hist_df
    except: pass


# ==============================================================================
# [탭 1] 도시가스 공급실적 관리
# ==============================================================================
def run_tab1_management():
    def load_excel_tab1(file):
        try:
            raw = pd.read_excel(file, sheet_name='연간', header=None)
        except:
            try: raw = pd.read_excel(file, sheet_name=0, header=None)
            except Exception as e: return None, f"❌ 읽기 실패: {e}"

        header_idx = None
        for i, row in raw.iterrows():
            vals = row.astype(str).values
            if '연' in vals and '월' in vals and '일' in vals:
                header_idx = i
                break
        
        if header_idx is None: return None, "❌ 헤더 없음"

        df = raw.iloc[header_idx+1:].copy()
        df.columns = raw.iloc[header_idx].astype(str).str.replace(r'\s+', '', regex=True).tolist()

        col_map = {}
        for c in df.columns:
            if '연' in c: col_map['y'] = c
            elif '월' in c: col_map['m'] = c
            elif '일' in c: col_map['d'] = c
            elif ('계획' in c or '예상' in c) and 'GJ' in c: col_map['p_gj'] = c
            elif '실적' in c and 'GJ' in c: col_map['a_gj'] = c
            elif ('계획' in c or '예상' in c) and 'm3' in c: col_map['p_m3'] = c
            elif '실적' in c and 'm3' in c: col_map['a_m3'] = c

        try:
            df['날짜'] = pd.to_datetime({
                'year': pd.to_numeric(df[col_map['y']], errors='coerce'),
                'month': pd.to_numeric(df[col_map['m']], errors='coerce'),
                'day': pd.to_numeric(df[col_map['d']], errors='coerce')
            }, errors='coerce')
            df = df.dropna(subset=['날짜'])
            df['날짜_str'] = df['날짜'].dt.strftime('%Y-%m-%d')

            df['계획(GJ)'] = pd.to_numeric(df[col_map.get('p_gj')], errors='coerce').fillna(0)
            df['실적(GJ)'] = pd.to_numeric(df[col_map.get('a_gj')], errors='coerce').fillna(0)
            df['계획(m3)'] = pd.to_numeric(df[col_map.get('p_m3')], errors='coerce').fillna(0)
            df['실적(m3)'] = pd.to_numeric(df[col_map.get('a_m3')], errors='coerce').fillna(0)
            
            df = df[['날짜', '날짜_str', '계획(GJ)', '실적(GJ)', '계획(m3)', '실적(m3)']]
        except Exception as e: return None, f"❌ 변환 오류: {e}"

        return df, None

    if uploaded_plan:
        df, err = load_excel_tab1(uploaded_plan)
        if not err: st.session_state.data_tab1 = df
    elif 'data_tab1' not in st.session_state:
        try:
            path = Path(__file__).parent / "2026_연간_일별공급계획_2.xlsx"
            if path.exists():
                df, err = load_excel_tab1(path)
                if not err: st.session_state.data_tab1 = df
        except: pass

    if 'data_tab1' not in st.session_state or st.session_state.data_tab1 is None:
        st.warning("👈 '2026 연간 계획' 파일을 업로드해주세요.")
        return

    df = st.session_state.data_tab1

    st.title("🔥 도시가스 공급실적 관리")

    col_date, col_space = st.columns([1, 5])
    with col_date:
        selected_date = st.date_input("조회 기준일", value=df['날짜'].min(), label_visibility="collapsed")
    
    target_str = selected_date.strftime('%Y-%m-%d')
    target_obj = pd.to_datetime(selected_date)

    mask_day = df['날짜_str'] == target_str
    mask_mtd = (df['날짜'] <= target_obj) & (df['날짜'].dt.month == target_obj.month) & (df['날짜'].dt.year == target_obj.year)
    mask_ytd = (df['날짜'] <= target_obj) & (df['날짜'].dt.year == target_obj.year)

    if not df[mask_day].empty:
        d_day = df[mask_day].iloc[0]
        day_p_gj, day_a_gj = d_day['계획(GJ)'], d_day['실적(GJ)']
        day_p_m3, day_a_m3 = d_day['계획(m3)']/1000, d_day['실적(m3)']/1000
    else:
        day_p_gj = day_a_gj = day_p_m3 = day_a_m3 = 0

    # 랭킹 계산 (실시간)
    rank_text = ""
    if 'history_df' in st.session_state and day_a_gj > 0:
        hist_df = st.session_state['history_df']
        # 안전장치: 컬럼 확인
        if 'year' in hist_df.columns and 'val_gj' in hist_df.columns:
            rank_all = (hist_df['val_gj'] > day_a_gj).sum() + 1
            month_vals = hist_df[hist_df['month'] == target_obj.month]['val_gj']
            rank_month = (month_vals > day_a_gj).sum() + 1
            firecracker = "🎉" if rank_all == 1 else ""
            rank_text = f"{firecracker} 🏆 역대 전체: {rank_all}위  /  📅 역대 {target_obj.month}월: {rank_month}위"
        else:
            rank_text = "⚠️ 과거 데이터 포맷 오류 (분석 탭 확인 필요)"

    st.markdown("### 🔥 열량 실적 (GJ)")
    c1, c2, c3 = st.columns(3)
    with c1:
        rate = (day_a_gj/day_p_gj*100) if day_p_gj>0 else 0
        st.metric(f"일간 달성률 {rate:.1f}%", f"{int(day_a_gj):,} GJ", f"{int(day_a_gj-day_p_gj):+,} GJ")
        st.caption(f"계획: {int(day_p_gj):,} GJ")
        if rank_text: st.info(rank_text)
        
    with c2:
        d = df[mask_mtd]
        p, a = d['계획(GJ)'].sum(), d['실적(GJ)'].sum()
        rate = (a/p*100) if p>0 else 0
        st.metric(f"월간 누적 {rate:.1f}%", f"{int(a):,} GJ", f"{int(a-p):+,} GJ")
        st.caption(f"누적 계획: {int(p):,}")
    with c3:
        d = df[mask_ytd]
        p, a = d['계획(GJ)'].sum(), d['실적(GJ)'].sum()
        rate = (a/p*100) if p>0 else 0
        st.metric(f"연간 누적 {rate:.1f}%", f"{int(a):,} GJ", f"{int(a-p):+,} GJ")
        st.caption(f"누적 계획: {int(p):,}")

    st.markdown("---")
    st.markdown("### 💧 부피 실적 (천 m³)")
    c4, c5, c6 = st.columns(3)
    with c4:
        rate = (day_a_m3/day_p_m3*100) if day_p_m3>0 else 0
        st.metric(f"일간 달성률 {rate:.1f}%", f"{int(day_a_m3):,} (천 m³)", f"{int(day_a_m3-day_p_m3):+,}")
    with c5:
        d = df[mask_mtd]
        p, a = d['계획(m3)'].sum()/1000, d['실적(m3)'].sum()/1000
        rate = (a/p*100) if p>0 else 0
        st.metric(f"월간 누적 {rate:.1f}%", f"{int(a):,} (천 m³)", f"{int(a-p):+,}")
    with c6:
        d = df[mask_ytd]
        p, a = d['계획(m3)'].sum()/1000, d['실적(m3)'].sum()/1000
        rate = (a/p*100) if p>0 else 0
        st.metric(f"연간 누적 {rate:.1f}%", f"{int(a):,} (천 m³)", f"{int(a-p):+,}")

    st.markdown("---")
    st.subheader(f"📝 {target_obj.month}월 실적 입력")
    st.info("💡 값을 입력하고 엔터(Enter)를 치면 즉시 랭킹이 바뀝니다!")

    mask_edit = (df['날짜'].dt.year == target_obj.year) & (df['날짜'].dt.month == target_obj.month)
    view_gj = df.loc[mask_edit, ['날짜', '계획(GJ)', '실적(GJ)']].copy()
    
    edited_gj = st.data_editor(
        view_gj,
        column_config={
            "날짜": st.column_config.DateColumn("공급일자", format="YYYY-MM-DD", disabled=True),
            "계획(GJ)": st.column_config.NumberColumn("계획(GJ)", format="%d", disabled=True),
            "실적(GJ)": st.column_config.NumberColumn("실적(GJ) ✏️", format="%d", min_value=0)
        },
        hide_index=True, use_container_width=True, key="editor_gj"
    )

    if not edited_gj.equals(view_gj):
        df.update(edited_gj)
        st.session_state.data_tab1 = df
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("##### 2️⃣ 부피(천 m³) 입력")
    view_m3_raw = df.loc[mask_edit, ['날짜', '계획(m3)', '실적(m3)']].copy()
    view_m3_disp = view_m3_raw.copy()
    view_m3_disp['계획(천m3)'] = (view_m3_raw['계획(m3)']/1000).round(0).astype(int)
    view_m3_disp['실적(천m3)'] = (view_m3_raw['실적(m3)']/1000).round(0).astype(int)
    view_m3_disp = view_m3_disp[['날짜', '계획(천m3)', '실적(천m3)']]

    edited_m3 = st.data_editor(
        view_m3_disp,
        column_config={
            "날짜": st.column_config.DateColumn("공급일자", format="YYYY-MM-DD", disabled=True),
            "계획(천m3)": st.column_config.NumberColumn("계획(천m³)", format="%d", disabled=True),
            "실적(천m3)": st.column_config.NumberColumn("실적(천m³) ✏️", format="%d", min_value=0)
        },
        hide_index=True, use_container_width=True, key="editor_m3"
    )

    if not edited_m3.equals(view_m3_disp):
        new_val = edited_m3['실적(천m3)'] * 1000
        df.loc[mask_edit, '실적(m3)'] = new_val.values
        st.session_state.data_tab1 = df
        st.rerun()

    st.markdown("---")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='연간', index=False)
    st.download_button("💾 관리 데이터 엑셀 저장", data=buffer, file_name=f"실적_{target_str}.xlsx")


# ==============================================================================
# [탭 2] 공급량 분석
# ==============================================================================
def run_tab2_analysis():
    def _render_supply_top_card(rank, row, icon, gradient):
        date_str = f"{int(row['year'])}년 {int(row['month'])}월 {int(row['day'])}일"
        supply_str = f"{row['val_gj']:,.1f} GJ"
        html = f"""<div style="border-radius:20px;padding:16px 20px;background:{gradient};box-shadow:0 4px 14px rgba(0,0,0,0.06);margin-top:8px;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;"><div style="font-size:26px;">{icon}</div><div style="font-size:15px;font-weight:700;">최대 공급량 {rank}위</div></div>
        <div style="font-size:14px;margin-bottom:3px;">📅 <b>{date_str}</b></div>
        <div style="font-size:14px;margin-bottom:3px;">🔥 공급량: <b>{supply_str}</b></div>
        </div>"""
        st.markdown(html, unsafe_allow_html=True)

    # 데이터 로드 (세션에 있는 clean data 사용)
    if 'history_df' not in st.session_state:
        st.info("👈 좌측 사이드바에서 '과거 실적(History)' 파일을 업로드해주세요.")
        return

    # KeyError 해결: 이미 load_history_data에서 컬럼명을 [year, month, day, val_gj]로 통일했습니다.
    df_clean = st.session_state['history_df'].copy()
    
    st.title("📊 도시가스 공급량 분석 (일별)")
    
    # 1. 기준 선택
    years = sorted(df_clean["year"].unique().tolist())
    def_year = 2026 if 2026 in years else (years[-1] if years else 2026)
    
    st.markdown("#### ✅ 분석 기준 선택")
    c1, c2 = st.columns([1, 4])
    with c1: 
        sel_year = st.selectbox("연도", years, index=years.index(def_year) if def_year in years else 0, key="t2_y")
        sel_month = st.selectbox("월", list(range(1, 13)), key="t2_m")

    st.markdown("---")
    
    # 2. 그래프
    st.markdown(f"### 📈 {sel_month}월 일별 패턴 비교")
    
    past_years = [y for y in years if y < sel_year][-3:] # 최근 3년
    sel_past = st.multiselect("비교할 과거 연도", [y for y in years if y < sel_year], default=past_years)
    
    fig = go.Figure()
    
    # 과거
    colors = ["#93C5FD", "#A5B4FC", "#C4B5FD", "#FDA4AF"]
    for i, y in enumerate(sel_past):
        sub = df_clean[(df_clean["year"] == y) & (df_clean["month"] == sel_month)]
        if sub.empty: continue
        col = colors[i % 4]
        width = 3 if y == sel_year - 1 else 1.5
        fig.add_scatter(x=sub["day"], y=sub["val_gj"], name=f"{y}년", line=dict(color=col, width=width))
        
    # 금년 (선택 연도)
    this_df = df_clean[(df_clean["year"] == sel_year) & (df_clean["month"] == sel_month)]
    if not this_df.empty:
        fig.add_scatter(x=this_df["day"], y=this_df["val_gj"], name=f"{sel_year}년", line=dict(color="black", width=4))
        
    fig.update_layout(height=450, margin=dict(t=30, b=10, l=10, r=10), xaxis_title="일", yaxis_title="공급량 (GJ)")
    st.plotly_chart(fig, use_container_width=True)

    # 3. Top 랭킹
    st.markdown("---")
    st.markdown(f"### 💎 {sel_month}월 공급량 Top 랭킹")
    
    # 월간 랭킹
    month_all = df_clean[df_clean["month"] == sel_month].sort_values("val_gj", ascending=False).head(5)
    month_all.insert(0, "Rank", range(1, len(month_all) + 1))
    
    if not month_all.empty:
        top3 = month_all.head(3)
        c1, c2, c3 = st.columns(3)
        icons, grads = ["🥇", "🥈", "🥉"], ["linear-gradient(120deg,#eff6ff,#fef9c3)", "linear-gradient(120deg,#f9fafb,#e5e7eb)", "linear-gradient(120deg,#fff7ed,#fef9c3)"]
        
        for i, (_, row) in enumerate(top3.iterrows()):
            with [c1, c2, c3][i]: _render_supply_top_card(int(row["Rank"]), row, icons[i], grads[i])
        
        st.dataframe(month_all[['Rank', 'year', 'month', 'day', 'val_gj']], use_container_width=True, hide_index=True)
    else:
        st.info("해당 월의 데이터가 없습니다.")


# ==============================================================================
# [메인 실행]
# ==============================================================================
if menu == "1. 도시가스 공급실적 관리":
    run_tab1_management()
else:
    run_tab2_analysis()
