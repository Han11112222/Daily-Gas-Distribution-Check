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
# [0] 페이지 기본 설정 (무조건 맨 윗줄)
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


# ==============================================================================
# [탭 1] 도시가스 공급실적 관리 (입력형 - 기존 유지)
# ==============================================================================
def run_tab1_management():
    # --- 내부 함수 ---
    def load_excel_tab1(file):
        try:
            raw = pd.read_excel(file, sheet_name='연간', header=None)
        except:
            try:
                raw = pd.read_excel(file, sheet_name=0, header=None)
            except Exception as e:
                return None, f"❌ 파일 읽기 실패: {e}"

        header_idx = None
        for i, row in raw.iterrows():
            vals = row.astype(str).values
            if '연' in vals and '월' in vals and '일' in vals:
                header_idx = i
                break
        
        if header_idx is None:
            return None, "❌ [연, 월, 일] 컬럼을 찾을 수 없습니다."

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

            df['계획(GJ)'] = pd.to_numeric(df[col_map.get('p_gj')], errors='coerce').fillna(0)
            df['실적(GJ)'] = pd.to_numeric(df[col_map.get('a_gj')], errors='coerce').fillna(0)
            df['계획(m3)'] = pd.to_numeric(df[col_map.get('p_m3')], errors='coerce').fillna(0)
            df['실적(m3)'] = pd.to_numeric(df[col_map.get('a_m3')], errors='coerce').fillna(0)
            
            df = df[['날짜', '계획(GJ)', '실적(GJ)', '계획(m3)', '실적(m3)']]
        except Exception as e:
            return None, f"❌ 데이터 변환 오류: {e}"

        return df, None

    if 'data_tab1' not in st.session_state:
        st.session_state.data_tab1 = None

    st.sidebar.header("📂 [관리] 데이터 파일")
    uploaded = st.sidebar.file_uploader("연간계획 엑셀 업로드", type=['xlsx'], key="u1")
    DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

    if uploaded:
        df, err = load_excel_tab1(uploaded)
        if not err: 
            st.session_state.data_tab1 = df
            st.sidebar.success("✅ 파일 로드 성공")
        else: st.sidebar.error(err)
    elif st.session_state.data_tab1 is None:
        try:
            path = Path(__file__).parent / DEFAULT_FILE
            if path.exists():
                df, err = load_excel_tab1(path)
                if not err: 
                    st.session_state.data_tab1 = df
                    st.sidebar.info(f"ℹ️ 기본 파일 사용 ({DEFAULT_FILE})")
            else:
                st.sidebar.warning(f"기본 파일({DEFAULT_FILE})이 없습니다.")
        except:
            pass

    if st.session_state.data_tab1 is None:
        st.warning("👈 좌측 사이드바에서 엑셀 파일을 업로드해주세요.")
        return

    df = st.session_state.data_tab1

    st.title("🔥 도시가스 공급실적 관리")

    col_date, col_space = st.columns([1, 5])
    with col_date:
        selected_date = st.date_input("조회 기준일", value=df['날짜'].min(), label_visibility="collapsed")
    target_date = pd.to_datetime(selected_date)

    def calc_kpi(data, t):
        mask_day = data['날짜'] == t
        mask_mtd = (data['날짜'] <= t) & (data['날짜'].dt.month == t.month) & (data['날짜'].dt.year == t.year)
        mask_ytd = (data['날짜'] <= t) & (data['날짜'].dt.year == t.year)
        
        res = {}
        for label, mask in zip(['Day', 'MTD', 'YTD'], [mask_day, mask_mtd, mask_ytd]):
            d = data[mask]
            p_gj = d['계획(GJ)'].sum()
            a_gj = d['실적(GJ)'].sum()
            diff_gj = a_gj - p_gj
            rate_gj = (a_gj / p_gj * 100) if p_gj > 0 else 0
            p_m3 = d['계획(m3)'].sum() / 1000
            a_m3 = d['실적(m3)'].sum() / 1000
            diff_m3 = a_m3 - p_m3
            rate_m3 = (a_m3 / p_m3 * 100) if p_m3 > 0 else 0
            res[label] = {
                'gj': {'p': p_gj, 'a': a_gj, 'diff': diff_gj, 'rate': rate_gj},
                'm3': {'p': p_m3, 'a': a_m3, 'diff': diff_m3, 'rate': rate_m3}
            }
        return res

    metrics = calc_kpi(df, target_date)

    st.markdown("### 🔥 열량 실적 (GJ)")
    col_g1, col_g2, col_g3 = st.columns(3)
    with col_g1:
        m = metrics['Day']['gj']
        st.metric(label=f"일간 달성률 {m['rate']:.1f}%", value=f"{int(m['a']):,} GJ", delta=f"{int(m['diff']):+,} GJ")
        st.caption(f"계획: {int(m['p']):,} GJ")
    with col_g2:
        m = metrics['MTD']['gj']
        st.metric(label=f"월간 누적 달성률 {m['rate']:.1f}%", value=f"{int(m['a']):,} GJ", delta=f"{int(m['diff']):+,} GJ")
        st.caption(f"누적 계획: {int(m['p']):,} GJ")
    with col_g3:
        m = metrics['YTD']['gj']
        st.metric(label=f"연간 누적 달성률 {m['rate']:.1f}%", value=f"{int(m['a']):,} GJ", delta=f"{int(m['diff']):+,} GJ")
        st.caption(f"누적 계획: {int(m['p']):,} GJ")

    st.markdown("---")
    st.markdown("### 💧 부피 실적 (천 m³)")
    col_m1, col_m2, col_m3 = st.columns(3)
    with col_m1:
        m = metrics['Day']['m3']
        st.metric(label=f"일간 달성률 {m['rate']:.1f}%", value=f"{int(m['a']):,} (천 m³)", delta=f"{int(m['diff']):+,}")
        st.caption(f"계획: {int(m['p']):,}")
    with col_m2:
        m = metrics['MTD']['m3']
        st.metric(label=f"월간 누적 달성률 {m['rate']:.1f}%", value=f"{int(m['a']):,} (천 m³)", delta=f"{int(m['diff']):+,}")
        st.caption(f"누적 계획: {int(m['p']):,}")
    with col_m3:
        m = metrics['YTD']['m3']
        st.metric(label=f"연간 누적 달성률 {m['rate']:.1f}%", value=f"{int(m['a']):,} (천 m³)", delta=f"{int(m['diff']):+,}")
        st.caption(f"누적 계획: {int(m['p']):,}")

    st.markdown("---")
    st.subheader(f"📝 {target_date.month}월 실적 입력")
    st.info("💡 값을 수정하고 엔터(Enter)를 치면 상단 그래프가 즉시 업데이트됩니다.")

    mask_month = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month)

    st.markdown("##### 1️⃣ 열량(GJ) 입력")
    view_gj = df.loc[mask_month, ['날짜', '계획(GJ)', '실적(GJ)']].copy()
    edited_gj = st.data_editor(
        view_gj,
        column_config={
            "날짜": st.column_config.DateColumn("공급일자", format="YYYY-MM-DD", disabled=True),
            "계획(GJ)": st.column_config.NumberColumn("계획(GJ)", format="%d", disabled=True),
            "실적(GJ)": st.column_config.NumberColumn("실적(GJ) ✏️", format="%d", min_value=0),
        },
        hide_index=True, use_container_width=True, key="editor_gj"
    )
    if not edited_gj.equals(view_gj):
        df.update(edited_gj)
        st.session_state.data_tab1 = df
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("##### 2️⃣ 부피(천 m³) 입력")
    view_m3_raw = df.loc[mask_month, ['날짜', '계획(m3)', '실적(m3)']].copy()
    view_m3_display = view_m3_raw.copy()
    view_m3_display['계획(천m3)'] = (view_m3_raw['계획(m3)'] / 1000).round(0).astype(int)
    view_m3_display['실적(천m3)'] = (view_m3_raw['실적(m3)'] / 1000).round(0).astype(int)
    view_m3_display = view_m3_display[['날짜', '계획(천m3)', '실적(천m3)']]

    edited_m3 = st.data_editor(
        view_m3_display,
        column_config={
            "날짜": st.column_config.DateColumn("공급일자", format="YYYY-MM-DD", disabled=True),
            "계획(천m3)": st.column_config.NumberColumn("계획(천m³)", format="%d", disabled=True),
            "실적(천m3)": st.column_config.NumberColumn("실적(천m³) ✏️", format="%d", min_value=0),
        },
        hide_index=True, use_container_width=True, key="editor_m3"
    )
    if not edited_m3.equals(view_m3_display):
        new_raw_m3 = edited_m3['실적(천m3)'] * 1000
        df.loc[mask_month, '실적(m3)'] = new_raw_m3.values
        st.session_state.data_tab1 = df
        st.rerun()

    st.markdown("---")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='연간', index=False)
    st.download_button(label="💾 관리 데이터 엑셀 저장", data=buffer, file_name=f"실적데이터_{target_date.strftime('%Y%m%d')}.xlsx", mime="application/vnd.ms-excel")


# ==============================================================================
# [탭 2] 공급량 분석 (Han형님 요청: 일별 분석 전용 + 2026 계획)
# ==============================================================================
def run_tab2_analysis():
    # --- 분석용 헬퍼 함수 ---
    COLOR_PLAN = "rgba(0, 90, 200, 1)"
    COLOR_ACT = "rgba(0, 150, 255, 1)"
    COLOR_DIFF = "rgba(0, 80, 160, 1)"

    def center_style(styler):
        styler = styler.set_properties(**{"text-align": "center"})
        styler = styler.set_table_styles([dict(selector="th", props=[("text-align", "center")])])
        return styler

    def pick_default_year_2026(years: List[int]) -> int:
        # Han형님 요청: 2026년이 있으면 2026년 우선, 없으면 2025년
        if 2026 in years: return 2026
        if 2025 in years: return 2025
        return years[-1]

    def load_supply_sheets(excel_bytes):
        xls = pd.ExcelFile(io.BytesIO(excel_bytes), engine="openpyxl")
        return (xls.parse("월별계획_실적") if "월별계획_실적" in xls.sheet_names else pd.DataFrame(),
                xls.parse("일별실적") if "일별실적" in xls.sheet_names else pd.DataFrame())

    def clean_supply_month_df(df):
        if df.empty: return df
        df = df.copy()
        if "Unnamed: 0" in df.columns: df = df.drop(columns=["Unnamed: 0"])
        df["연"] = pd.to_numeric(df["연"], errors="coerce").astype("Int64")
        df["월"] = pd.to_numeric(df["월"], errors="coerce").astype("Int64")
        # 컬럼 이름에 '계획', '실적' 등이 들어간 숫자 데이터 처리
        num_cols = [c for c in df.columns if c not in ["연", "월"]]
        for c in num_cols: 
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
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
        # 기본값 2026년으로 설정
        default_year = pick_default_year_2026(years_all)
        
        c1, c2, c3 = st.columns([1.2, 1.2, 1.6])
        with c1: 
            sel_year = st.selectbox("기준 연도", years_all, index=years_all.index(default_year), key=f"{key_prefix}year")
        with c2: 
            # 1~12월 선택 (기본 1월)
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
        <div style="font-size:14px;">🌡 평균기온: <b>{temp_str}</b></div></div>"""
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
        
        # 1. 계획 컬럼 자동 찾기 (사업계획 우선)
        plan_cols = [c for c in month_df.columns if "계획" in c and "MJ" in c]
        if not plan_cols:
            st.warning("월별 계획(MJ) 컬럼을 찾을 수 없습니다.")
            return
        
        # 사업계획이 포함된 컬럼 우선 선택, 없으면 첫 번째 것
        biz_plan_cols = [c for c in plan_cols if "사업계획" in c]
        target_plan_col = biz_plan_cols[0] if biz_plan_cols else plan_cols[0]
        
        # 2. 월 계획값 및 일일 계획량 계산
        mrow = month_df[(month_df["연"] == sel_year) & (month_df["월"] == sel_month)]
        
        # 2026년 데이터가 없어도 계획은 그릴 수 있도록 처리 (값이 없으면 0)
        if mrow.empty:
            month_plan_mj = 0
        else:
            month_plan_mj = float(mrow.iloc[0][target_plan_col])
            
        try:
            days_in_month = int(pd.Timestamp(sel_year, sel_month, 1).days_in_month)
        except:
            days_in_month = 30 # 에러 방지용 기본값
            
        daily_plan_mj = month_plan_mj / days_in_month
        daily_plan_gj = daily_plan_mj / 1000.0

        # 데이터 정리
        df_all = day_df.copy()
        df_all["연"] = df_all["일자"].dt.year
        df_all["월"] = df_all["일자"].dt.month
        df_all["일"] = df_all["일자"].dt.day
        this_df = df_all[(df_all["연"] == sel_year) & (df_all["월"] == sel_month)].copy()
        
        # 3. 차트 그리기
        st.markdown("### 📈 일별 패턴 비교(당년도 vs 과거동월)")
        cand_years = sorted(df_all["연"].unique().tolist())
        past_candidates = [y for y in cand_years if y < sel_year]
        past_recent_10 = past_candidates[-10:]
        default_past = [y for y in [sel_year - 1] if y in past_recent_10]
        past_years = st.multiselect("과거 연도 선택", options=past_recent_10, default=default_past, key=f"{key_prefix}past_years")
        
        fig1 = go.Figure()
        
        # (1) 당년도 실적 (데이터가 있을 때만)
        if not this_df.empty: 
            fig1.add_scatter(
                x=this_df["일"], y=this_df[act_col] / 1000.0, 
                mode="lines+markers", 
                name=f"{sel_year}년 {sel_month}월 실적", 
                line=dict(color=COLOR_ACT, width=3)
            )
            
        # (2) 과거 연도 실적
        for y in past_years:
            sub = df_all[(df_all["연"] == y) & (df_all["월"] == sel_month)].copy()
            if sub.empty: continue
            fig1.add_scatter(
                x=sub["일"], y=sub[act_col] / 1000.0, 
                mode="lines+markers", 
                name=f"{y}년 {sel_month}월 실적", 
                line=dict(width=1.5, dash="dot")
            )
            
        # (3) [Han형님 요청] 선택 연도 일일 계획량 (점선)
        # 데이터가 없어도 계획선은 그립니다.
        fig1.add_scatter(
            x=list(range(1, days_in_month + 1)), 
            y=[daily_plan_gj] * days_in_month, 
            mode="lines", 
            name=f"{sel_year}년 {sel_month}월 계획(사업계획)", 
            line=dict(color=COLOR_PLAN, width=3, dash="dot")
        )
        
        fig1.update_layout(
            title=f"{sel_year}년 {sel_month}월 일별 공급량 패턴", 
            xaxis_title="일", 
            yaxis_title="공급량 (GJ)", 
            margin=dict(l=10, r=10, t=50, b=10)
        )
        st.plotly_chart(fig1, use_container_width=True)

        # 4. 편차 그래프 (실적이 있을 때만)
        if not this_df.empty:
            st.markdown("### 🧮 일일계획 대비 편차 (당년도)")
            this_df["편차_GJ"] = (this_df[act_col] - daily_plan_mj) / 1000.0
            fig2 = go.Figure()
            fig2.add_bar(x=this_df["일"], y=this_df["편차_GJ"], name="편차", marker_color=COLOR_DIFF)
            fig2.update_layout(title=f"{sel_year}년 {sel_month}월 편차(실적-일계획)", xaxis_title="일", yaxis_title="편차 (GJ)", margin=dict(l=10, r=10, t=40, b=10))
            st.plotly_chart(fig2, use_container_width=True)
            
            show = this_df[["일자", act_col, "편차_GJ"]].copy()
            show.columns = ["일자", "일별실적(GJ)", "편차(GJ)"]
            show["일별실적(GJ)"] = show["일별실적(GJ)"].apply(lambda v: v / 1000.0)
            st.dataframe(center_style(show.style.format("{:,.1f}", subset=["일별실적(GJ)", "편차(GJ)"])), use_container_width=True, hide_index=True)

        # 5. Top 랭킹
        st.markdown("---")
        st.markdown("### 💎 일별 공급량 Top 랭킹")
        month_all = df_all[df_all["월"] == sel_month].copy()
        if not month_all.empty:
            top_n = st.slider("표시할 순위 개수", 5, 50, 10, 5, key=f"{key_prefix}top_n")
            
            # [Han형님 요청] **월 표기
            st.markdown(f"#### 📅 {sel_month}월 기준 Top 랭킹")
            month_all["공급량_GJ"] = month_all[act_col] / 1000.0
            rank_df = month_all.sort_values("공급량_GJ", ascending=False).head(top_n).copy()
            rank_df.insert(0, "Rank", range(1, len(rank_df) + 1))
            top3 = rank_df.head(3)
            c1, c2, c3 = st.columns(3)
            cols = [c1, c2, c3]
            icons, grads = ["🥇", "🥈", "🥉"], ["linear-gradient(120deg,#eff6ff,#fef9c3)", "linear-gradient(120deg,#f9fafb,#e5e7eb)", "linear-gradient(120deg,#fff7ed,#fef9c3)"]
            for i, (_, row) in enumerate(top3.iterrows()):
                with cols[i]: _render_supply_top_card(int(row["Rank"]), row, icons[i], grads[i])
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
                with gcols[i]: _render_supply_top_card(int(row["Rank"]), row, icons[i], grads[i])
            st.dataframe(center_style(global_top[["Rank", "공급량_GJ", "연", "월", "일", "평균기온(℃)"]].style.format({"공급량_GJ": "{:,.1f}", "평균기온(℃)": "{:,.1f}"})), use_container_width=True, hide_index=True)

            st.markdown("#### 🌡️ 기온별 공급량 변화 (3차 다항식)")
            temp_supply = month_all.dropna(subset=["평균기온(℃)", act_col]).copy()
            if len(temp_supply) > 4:
                x = temp_supply["평균기온(℃)"].values
                y = temp_supply[act_col].values / 1000.0
                coeffs = np.polyfit(x, y, 3)
                p = np.poly1d(coeffs)
                xs = np.linspace(x.min() - 1, x.max() + 1, 150)
                fig3 = go.Figure()
                fig3.add_scatter(x=x, y=y, mode="markers", name="일별 데이터", marker=dict(size=7, opacity=0.7))
                fig3.add_scatter(x=xs, y=p(xs), mode="lines", name="3차 다항 회귀", line=dict(color=COLOR_DIFF, width=2))
                fig3.update_layout(title=f"{sel_month}월 기온별 공급량", xaxis_title="기온(℃)", yaxis_title="공급량 (GJ)", margin=dict(l=10, r=10, t=40, b=10))
                st.plotly_chart(fig3, use_container_width=True)

        st.markdown("---")
        temperature_matrix(day_df, sel_month, key_prefix + "temp_")
        temperature_supply_band_section(day_df, sel_month, key_prefix + "band_")

    # --- 실행 로직 (Tab 2 Main) ---
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
            # plan_choice, plan_label 자동 처리되므로 인자는 None으로 넘기거나 함수 내부에서 처리
            # 여기서는 함수 내부에서 자동으로 사업계획을 찾도록 변경했으므로, 
            # 호출 시 인자를 맞춰줍니다. (dummy 인자 전달)
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
