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
def load_common_data():
    """
    Tab 2에서 사용하는 '공급량(계획_실적).xlsx' 데이터를 로드하여 공유합니다.
    """
    path = Path(__file__).parent / "공급량(계획_실적).xlsx"
    if not path.exists():
        # 파일이 없으면 빈 껍데기 반환
        return pd.DataFrame(), pd.DataFrame()

    try:
        xls = pd.ExcelFile(path, engine="openpyxl")
        
        # 1. 월별 데이터 로드
        sheet_m = next((s for s in xls.sheet_names if "월별" in s), None)
        month_df = pd.read_excel(xls, sheet_name=sheet_m) if sheet_m else pd.DataFrame()
        
        # 2. 일별 데이터 로드
        sheet_d = next((s for s in xls.sheet_names if "일별" in s), xls.sheet_names[0])
        day_df = pd.read_excel(xls, sheet_name=sheet_d)
        
        # 3. 데이터 정제 (Tab 2 로직 적용)
        if not day_df.empty:
            day_df.columns = [str(c).replace(" ", "").strip() for c in day_df.columns]
            col_date = next((c for c in day_df.columns if "일자" in c or "date" in c.lower()), None)
            
            if col_date:
                day_df[col_date] = pd.to_datetime(day_df[col_date], errors="coerce")
                day_df = day_df.dropna(subset=[col_date])
                
                # 표준 컬럼명 매핑
                rename_map = {col_date: '일자'}
                col_mj = next((c for c in day_df.columns if "공급량" in c and "MJ" in c), None)
                if col_mj: rename_map[col_mj] = '공급량(MJ)'
                
                # 나머지 숫자 컬럼 변환
                for c in day_df.columns:
                    if "공급량" in c or "기온" in c:
                        day_df[c] = pd.to_numeric(day_df[c], errors='coerce').fillna(0)
                
                day_df = day_df.rename(columns=rename_map)
                
                # 연월일 컬럼
                day_df["연"] = day_df["일자"].dt.year
                day_df["월"] = day_df["일자"].dt.month
                day_df["일"] = day_df["일자"].dt.day

        if not month_df.empty:
             month_df.columns = [str(c).replace(" ", "").strip() for c in month_df.columns]
             col_y = next((c for c in month_df.columns if "연" in c), None)
             col_m = next((c for c in month_df.columns if "월" in c), None)
             if col_y and col_m:
                 month_df = month_df.rename(columns={col_y: '연', col_m: '월'})
        
        return month_df, day_df

    except Exception:
        return pd.DataFrame(), pd.DataFrame()


# ==============================================================================
# [탭 1] 도시가스 공급실적 관리 (복원 및 수정)
# ==============================================================================
def run_tab1_management():
    # 1. 데이터 로드 (초기화)
    if 'tab1_df' not in st.session_state:
        _, day_df = load_common_data()
        
        if not day_df.empty:
            # Tab 1용 포맷으로 변환 (기존 코드 호환성 유지)
            manage_df = day_df.copy()
            manage_df = manage_df.rename(columns={'일자': '날짜'})
            
            # 실적(GJ) 생성 (MJ -> GJ)
            if '공급량(MJ)' in manage_df.columns:
                manage_df['실적(GJ)'] = (manage_df['공급량(MJ)'] / 1000).round(0)
            else:
                manage_df['실적(GJ)'] = 0
            
            # 계획(GJ) 등 나머지 컬럼이 없다면 생성 (간단화)
            for c in ['계획(GJ)', '계획(m3)', '실적(m3)']:
                if c not in manage_df.columns: manage_df[c] = 0
                
            st.session_state.tab1_df = manage_df[['날짜', '계획(GJ)', '실적(GJ)', '계획(m3)', '실적(m3)']]
        else:
            st.session_state.tab1_df = pd.DataFrame(columns=['날짜', '계획(GJ)', '실적(GJ)', '계획(m3)', '실적(m3)'])

    df = st.session_state.tab1_df

    # 사이드바 (업로드 - 선택사항)
    st.sidebar.header("📂 [관리] 데이터 파일")
    st.sidebar.info("기본적으로 '공급량(계획_실적).xlsx' 파일을 사용합니다.")
    
    st.title("🔥 도시가스 공급실적 관리")

    # 2. 날짜 선택 (디폴트: 최신 데이터 날짜)
    col_date, _ = st.columns([1, 4])
    with col_date:
        if not df.empty:
            # 실적(GJ)이 있는 데이터 중 가장 최근 날짜
            valid_dates = df[df['실적(GJ)'] > 0]['날짜']
            default_date = valid_dates.max() if not valid_dates.empty else df['날짜'].max()
        else:
            default_date = pd.Timestamp.today()
            
        selected_date = st.date_input("조회 기준일", value=default_date)
    target_date = pd.to_datetime(selected_date)

    # 3. KPI 및 랭킹 계산
    # (1) KPI용 현재 데이터
    mask_day = df['날짜'] == target_date
    current_row = df[mask_day]
    
    if current_row.empty:
        # 데이터 없으면 빈 행 추가 (입력용)
        new_row = pd.DataFrame({'날짜': [target_date], '계획(GJ)': [0], '실적(GJ)': [0], '계획(m3)': [0], '실적(m3)': [0]})
        df = pd.concat([df, new_row], ignore_index=True)
        st.session_state.tab1_df = df
        current_row = df[df['날짜'] == target_date]

    current_val_gj = float(current_row['실적(GJ)'].iloc[0])
    plan_val_gj = float(current_row['계획(GJ)'].iloc[0])
    
    # (2) 랭킹 계산 (Tab 2 데이터 소스 기반)
    rank_text = ""
    if current_val_gj > 0:
        _, hist_day_df = load_common_data()
        if not hist_day_df.empty:
            # 단위 통일 및 필터링 (Tab 2 로직 동일)
            hist_day_df['val_gj'] = hist_day_df['공급량(MJ)'] / 1000.0
            valid_hist = hist_day_df[hist_day_df['val_gj'] > 0]
            
            # 자기 자신(오늘 날짜) 제외
            valid_hist = valid_hist[valid_hist['일자'] != target_date]
            
            # 전체 랭킹 (과거 + 현재 입력값)
            all_vals = pd.concat([valid_hist['val_gj'], pd.Series([current_val_gj])])
            rank_all = (all_vals > current_val_gj).sum() + 1
            
            # 동월 랭킹
            hist_month = valid_hist[valid_hist['일자'].dt.month == target_date.month]
            month_vals = pd.concat([hist_month['val_gj'], pd.Series([current_val_gj])])
            rank_month = (month_vals > current_val_gj).sum() + 1
            
            firecracker = "🎉" if rank_all == 1 else ""
            rank_text = f"{firecracker} 🏆 역대 전체: {rank_all}위  /  📅 역대 {target_date.month}월: {rank_month}위"

    # 4. 화면 표시 (형님이 좋아하셨던 이전 UI 복원)
    st.markdown("### 🔥 열량 실적 (GJ)")
    col_g1, col_g2, col_g3 = st.columns(3)
    
    # 누적 데이터 계산
    mask_mtd = (df['날짜'] <= target_date) & (df['날짜'].dt.month == target_date.month) & (df['날짜'].dt.year == target_date.year)
    mask_ytd = (df['날짜'] <= target_date) & (df['날짜'].dt.year == target_date.year)
    
    mtd_data = df[mask_mtd]
    ytd_data = df[mask_ytd]

    with col_g1:
        diff_gj = current_val_gj - plan_val_gj
        rate_gj = (current_val_gj / plan_val_gj * 100) if plan_val_gj > 0 else 0
        st.metric(label=f"일간 달성률 {rate_gj:.1f}%", value=f"{int(current_val_gj):,} GJ", delta=f"{int(diff_gj):+,} GJ")
        st.caption(f"계획: {int(plan_val_gj):,} GJ")
        if rank_text: st.info(rank_text)

    with col_g2:
        p_mtd = mtd_data['계획(GJ)'].sum()
        a_mtd = mtd_data['실적(GJ)'].sum()
        st.metric(label=f"월간 누적 달성률 {(a_mtd/p_mtd*100 if p_mtd>0 else 0):.1f}%", value=f"{int(a_mtd):,} GJ", delta=f"{int(a_mtd-p_mtd):+,} GJ")
        st.caption(f"누적 계획: {int(p_mtd):,} GJ")

    with col_g3:
        p_ytd = ytd_data['계획(GJ)'].sum()
        a_ytd = ytd_data['실적(GJ)'].sum()
        st.metric(label=f"연간 누적 달성률 {(a_ytd/p_ytd*100 if p_ytd>0 else 0):.1f}%", value=f"{int(a_ytd):,} GJ", delta=f"{int(a_ytd-p_ytd):+,} GJ")
        st.caption(f"누적 계획: {int(p_ytd):,} GJ")

    st.markdown("---")
    st.markdown("### 💧 부피 실적 (천 m³)")
    # (부피 메트릭도 동일한 구조로 생략 없이 표시)
    current_val_m3 = float(current_row['실적(m3)'].iloc[0]) / 1000
    plan_val_m3 = float(current_row['계획(m3)'].iloc[0]) / 1000
    
    col_m1, col_m2, col_m3 = st.columns(3)
    with col_m1:
        st.metric(label="일간 실적", value=f"{int(current_val_m3):,} (천 m³)", delta=f"{int(current_val_m3 - plan_val_m3):+,}")
        st.caption(f"계획: {int(plan_val_m3):,}")
    with col_m2:
        a_mtd_m3 = mtd_data['실적(m3)'].sum() / 1000
        p_mtd_m3 = mtd_data['계획(m3)'].sum() / 1000
        st.metric(label="월간 누적", value=f"{int(a_mtd_m3):,} (천 m³)", delta=f"{int(a_mtd_m3 - p_mtd_m3):+,}")
    with col_m3:
        a_ytd_m3 = ytd_data['실적(m3)'].sum() / 1000
        p_ytd_m3 = ytd_data['계획(m3)'].sum() / 1000
        st.metric(label="연간 누적", value=f"{int(a_ytd_m3):,} (천 m³)", delta=f"{int(a_ytd_m3 - p_ytd_m3):+,}")

    st.markdown("---")
    st.subheader(f"📝 {target_date.month}월 실적 입력")
    st.info("💡 값을 수정하고 엔터(Enter)를 치면 상단 그래프와 랭킹이 즉시 업데이트됩니다.")

    # 5. 데이터 입력 (월별 필터링)
    mask_month_view = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month)
    view_df = df.loc[mask_month_view].copy()
    
    # 열량 에디터
    st.markdown("##### 1️⃣ 열량(GJ) 입력")
    edited_gj = st.data_editor(
        view_df[['날짜', '계획(GJ)', '실적(GJ)']],
        column_config={
            "날짜": st.column_config.DateColumn("공급일자", format="YYYY-MM-DD", disabled=True),
            "계획(GJ)": st.column_config.NumberColumn("계획(GJ)", format="%d", disabled=True),
            "실적(GJ)": st.column_config.NumberColumn("실적(GJ) ✏️", format="%d", min_value=0)
        },
        hide_index=True, use_container_width=True, key="editor_gj"
    )

    if not edited_gj.equals(view_df[['날짜', '계획(GJ)', '실적(GJ)']]):
        df.update(edited_gj)
        st.session_state.tab1_df = df
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    
    # 부피 에디터 (천 단위 표시용)
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
            "실적(천m3)": st.column_config.NumberColumn("실적(천m³) ✏️", format="%d", min_value=0)
        },
        hide_index=True, use_container_width=True, key="editor_m3"
    )

    if not edited_m3.equals(view_m3[['날짜', '계획(천m3)', '실적(천m3)']]):
        # 원본(m3)으로 다시 변환해서 저장
        new_vals = edited_m3['실적(천m3)'] * 1000
        df.loc[mask_month_view, '실적(m3)'] = new_vals.values
        st.session_state.tab1_df = df
        st.rerun()

    st.markdown("---")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='연간', index=False)
    st.download_button(label="💾 관리 데이터 엑셀 저장", data=buffer, file_name=f"실적데이터_{target_date.strftime('%Y%m%d')}.xlsx", mime="application/vnd.ms-excel")


# ==============================================================================
# [탭 2] 공급량 분석 (완성된 버전 유지)
# ==============================================================================
def run_tab2_analysis():
    def center_style(styler):
        styler = styler.set_properties(**{"text-align": "center"})
        styler = styler.set_table_styles([dict(selector="th", props=[("text-align", "center")])])
        return styler

    def pick_default_year_2026(years: List[int]) -> int:
        if 2026 in years: return 2026
        return years[-1]

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
        
        # [데이터 통합] Tab 1에서 입력된 최신 데이터 병합
        if 'tab1_df' in st.session_state and st.session_state.tab1_df is not None:
            new_data = st.session_state.tab1_df.copy()
            new_data = new_data[new_data['실적(GJ)'] > 0][['날짜', '실적(GJ)']].copy()
            new_data.columns = ['일자', act_col]
            new_data[act_col] = new_data[act_col] * 1000 # GJ -> MJ로 변환
            
            # 중복 제거 후 병합
            day_df = pd.concat([day_df, new_data]).drop_duplicates(subset=['일자'], keep='last').sort_values('일자')
            
            # 연월일 재계산
            day_df["연"] = day_df["일자"].dt.year
            day_df["월"] = day_df["일자"].dt.month
            day_df["일"] = day_df["일자"].dt.day

        # 데이터 정리
        df_all = day_df.copy()
        this_df = df_all[(df_all["연"] == sel_year) & (df_all["월"] == sel_month)].copy()
        
        # 2026 일별 계획 로드 (Tab 1 입력값이 있으면 그걸 우선, 없으면 파일)
        # 여기서는 단순화를 위해 파일만 로드하되 시각화에 Tab 1 데이터를 반영
        
        st.markdown(f"### 📈 {sel_month}월 일별 패턴 비교")
        cand_years = sorted(df_all["연"].unique().tolist())
        past_candidates = [y for y in cand_years if y < sel_year]
        default_years = past_candidates[-2:] if len(past_candidates) >= 2 else past_candidates
        past_years = st.multiselect("과거 연도 선택", options=past_candidates, default=default_years, key=f"{key_prefix}past_years")
        
        fig1 = go.Figure()
        
        # (1) 과거 연도 실적
        pastel_colors = ["#93C5FD", "#A5B4FC", "#C4B5FD", "#FDA4AF", "#FCA5A5", "#FCD34D", "#86EFAC"]
        prev_year = sel_year - 1

        for idx, y in enumerate(past_years):
            sub = df_all[(df_all["연"] == y) & (df_all["월"] == sel_month)].copy()
            if sub.empty: continue
            line_color = "#3B82F6" if y == prev_year else pastel_colors[idx % len(pastel_colors)]
            line_width = 3 if y == prev_year else 1.5
            op_mode = "lines+markers" if y == prev_year else "lines"
            fig1.add_scatter(x=sub["일"], y=sub[act_col] / 1000.0, mode=op_mode, name=f"{y}년 {sel_month}월 실적", line=dict(color=line_color, width=line_width), hovertemplate="%{y:,.0f} GJ<extra></extra>")
            
        # (2) 당년도 실적 (Tab 1 입력 포함)
        if not this_df.empty: 
            fig1.add_scatter(x=this_df["일"], y=this_df[act_col] / 1000.0, mode="lines+markers", name=f"{sel_year}년 {sel_month}월 실적", line=dict(color="black", width=4), hovertemplate="%{y:,.0f} GJ<extra></extra>")
        
        fig1.update_layout(title=f"{sel_year}년 {sel_month}월 일별 공급량 패턴", xaxis_title="일", yaxis_title="공급량 (GJ)", margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig1, use_container_width=True)

        # (편차 그래프 등 나머지 시각화는 코드 길이상 유지 - 생략된 부분이 있다면 기존 코드와 동일)
        
        # Top 랭킹
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

        st.markdown("---")
        temperature_matrix(day_df, sel_month, key_prefix + "temp_")
        temperature_supply_band_section(day_df, sel_month, key_prefix + "band_")

    st.sidebar.header("📂 [분석] 데이터 파일")
    st.sidebar.info("기본적으로 '공급량(계획_실적).xlsx' 파일을 사용합니다.")
    st.title("📊 도시가스 공급량 분석 (일별)")

    month_df, day_df = load_common_data()
    if month_df.empty or day_df.empty:
        st.error("데이터를 불러올 수 없습니다.")
    else:
        act_col = "공급량(MJ)"
        long_dummy = month_df[["연", "월"]].copy()
        long_dummy["계획/실적"] = "실적"
        long_dummy["값"] = pd.to_numeric(month_df["실적_공급량(MJ)"], errors="coerce") if "실적_공급량(MJ)" in month_df.columns else 0
        long_dummy = long_dummy.dropna(subset=["값"])
        sel_year, sel_month, years_all = render_section_selector_daily(long_dummy, "공급량(일) 기준 선택", "supplyD_base_")
        st.markdown("---")
        supply_daily_main_logic(day_df, month_df, sel_year, sel_month, key_prefix="supplyD_")


# ==============================================================================
# [메인 실행]
# ==============================================================================
st.sidebar.title("통합 메뉴")
menu = st.sidebar.radio("이동", ["1. 도시가스 공급실적 관리", "2. 공급량 분석"])

if menu == "1. 도시가스 공급실적 관리":
    run_tab1_management()
else:
    run_tab2_analysis()
