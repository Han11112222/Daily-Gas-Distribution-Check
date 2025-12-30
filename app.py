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
# [공통] 페이지 기본 설정 (코드 최상단 필수 - 중복 금지)
# ─────────────────────────────────────────────────────────
st.set_page_config(page_title="도시가스 통합 관리 시스템", layout="wide")

# ─────────────────────────────────────────────────────────
# [공통] 한글 폰트 설정
# ─────────────────────────────────────────────────────────
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
# [탭 1] 도시가스 공급실적 관리 (입력 및 관리 기능)
# ==============================================================================
def app_performance_management():
    # 내부 함수: 엑셀 읽기
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

    # 사이드바 설정
    st.sidebar.markdown("---")
    st.sidebar.header("📂 실적 데이터 (관리용)")
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
            df, err = load_excel_tab1(DEFAULT_FILE)
            if not err: 
                st.session_state.data_tab1 = df
                st.sidebar.info("ℹ️ 기본 파일 사용 중")
        except:
            st.sidebar.warning("기본 파일을 찾을 수 없습니다. (2026_연간_일별공급계획_2.xlsx)")

    if st.session_state.data_tab1 is None:
        st.info("좌측 사이드바에서 엑셀 파일을 업로드하거나 기본 파일을 확인해주세요.")
        return

    df = st.session_state.data_tab1

    # --- 메인 화면 ---
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
    st.download_button(label="💾 데이터 엑셀로 저장", data=buffer, file_name=f"실적데이터_{target_date.strftime('%Y%m%d')}.xlsx", mime="application/vnd.ms-excel")


# ==============================================================================
# [탭 2] 공급량 분석 (Han형님 요청 분석 코드)
# ==============================================================================
def app_supply_analysis():
    DEFAULT_SALES_XLSX = "판매량(계획_실적).xlsx"
    DEFAULT_SUPPLY_XLSX = "공급량(계획_실적).xlsx"

    # 엑셀 헤더 → 분석 그룹 매핑
    USE_COL_TO_GROUP: Dict[str, str] = {
        "취사용": "가정용", "개별난방용": "가정용", "중앙난방용": "가정용", "자가열전용": "가정용",
        "일반용": "영업용", "업무난방용": "업무용", "냉방용": "업무용", "주한미군": "업무용",
        "산업용": "산업용", "수송용(CNG)": "수송용", "수송용(BIO)": "수송용",
        "열병합용": "열병합", "열병합용1": "열병합", "열병합용2": "열병합",
        "연료전지용": "연료전지", "열전용설비용": "열전용설비용",
    }
    GROUP_OPTIONS = ["총량", "가정용", "영업용", "업무용", "산업용", "수송용", "열병합", "연료전지", "열전용설비용"]
    COLOR_PLAN, COLOR_ACT, COLOR_PREV, COLOR_DIFF = "rgba(0, 90, 200, 1)", "rgba(0, 150, 255, 1)", "rgba(190, 190, 190, 1)", "rgba(0, 80, 160, 1)"

    # Helper Functions (Global Scope to Analysis)
    def fmt_num_safe(v): return "-" if pd.isna(v) else f"{float(v):,.0f}"
    def fmt_rate(v): return "-" if pd.isna(v) or np.isnan(v) else f"{float(v):,.1f}%"
    def center_style(styler):
        styler = styler.set_properties(**{"text-align": "center"})
        styler = styler.set_table_styles([dict(selector="th", props=[("text-align", "center")])])
        return styler
    def _clean_base(df):
        out = df.copy()
        if "Unnamed: 0" in out.columns: out = out.drop(columns=["Unnamed: 0"])
        out["연"] = pd.to_numeric(out["연"], errors="coerce").astype("Int64")
        out["월"] = pd.to_numeric(out["월"], errors="coerce").astype("Int64")
        return out
    def keyword_group(col):
        c = str(col)
        if "열병합" in c: return "열병합"
        if "연료전지" in c: return "연료전지"
        if "수송용" in c: return "수송용"
        if "열전용" in c: return "열전용설비용"
        if c in ["산업용"]: return "산업용"
        if c in ["일반용"]: return "영업용"
        if any(k in c for k in ["취사용", "난방용", "자가열"]): return "가정용"
        if any(k in c for k in ["업무", "냉방", "주한미군"]): return "업무용"
        return None
    def make_long(plan_df, actual_df):
        plan_df, actual_df = _clean_base(plan_df), _clean_base(actual_df)
        records = []
        for label, df in [("계획", plan_df), ("실적", actual_df)]:
            for col in df.columns:
                if col in ["연", "월"]: continue
                group = USE_COL_TO_GROUP.get(col) or keyword_group(col)
                if group is None: continue
                base = df[["연", "월"]].copy()
                base["그룹"], base["용도"], base["계획/실적"], base["값"] = group, col, label, pd.to_numeric(df[col], errors="coerce").fillna(0.0)
                records.append(base)
        if not records: return pd.DataFrame(columns=["연", "월", "그룹", "용도", "계획/실적", "값"])
        long_df = pd.concat(records, ignore_index=True).dropna(subset=["연", "월"])
        long_df["연"], long_df["월"] = long_df["연"].astype(int), long_df["월"].astype(int)
        return long_df
    def load_all_sheets(excel_bytes):
        xls = pd.ExcelFile(io.BytesIO(excel_bytes), engine="openpyxl")
        return {name: xls.parse(name) for name in ["계획_부피", "실적_부피", "계획_열량", "실적_열량"] if name in xls.sheet_names}
    def build_long_dict(sheets):
        long_dict = {}
        if "계획_부피" in sheets and "실적_부피" in sheets: long_dict["부피"] = make_long(sheets["계획_부피"], sheets["실적_부피"])
        if "계획_열량" in sheets and "실적_열량" in sheets: long_dict["열량"] = make_long(sheets["계획_열량"], sheets["실적_열량"])
        return long_dict
    def pick_default_year(years): return 2025 if 2025 in years else years[-1]
    def apply_period_filter(df, sel_year, sel_month, agg_mode):
        if df.empty: return df
        base = df[df["연"] == sel_year].copy()
        return base[base["월"] == sel_month] if agg_mode == "당월" else base[base["월"] <= sel_month]
    def apply_period_filter_multi_years(df, sel_month, agg_mode, years):
        if df.empty: return df
        base = df[df["연"].isin(years)].copy()
        return base[base["월"] == sel_month] if agg_mode == "당월" else base[base["월"] <= sel_month]
    def render_section_selector(long_df, title, key_prefix, fixed_mode=None, show_mode=True):
        st.markdown(f"#### ✅ {title} 기준 선택")
        if long_df.empty:
            st.info("연도 정보가 없습니다.")
            return 0, 1, "연 누적", []
        years_all = sorted(long_df["연"].unique().tolist())
        default_year = pick_default_year(years_all)
        c1, c2, c3 = st.columns([1.2, 1.2, 1.6])
        with c1: sel_year = st.selectbox("기준 연도", years_all, index=years_all.index(default_year), key=f"{key_prefix}year")
        with c2: sel_month = st.selectbox("기준 월", list(range(1, 13)), index=9, key=f"{key_prefix}month") # Default Oct (10월)
        if fixed_mode:
            agg_mode = fixed_mode
            with c3: st.markdown(f"<div style='padding-top:28px;font-size:14px;color:#666;'>집계 기준: <b>{fixed_mode}</b></div>", unsafe_allow_html=True)
        else:
            with c3: agg_mode = st.radio("집계 기준", ["당월", "연 누적"], index=0, horizontal=True, key=f"{key_prefix}mode") if show_mode else "연 누적"
        st.markdown(f"<div style='margin-top:-4px;font-size:13px;color:#666;'>선택 기준: <b>{sel_year}년 {sel_month}월</b> · {agg_mode}</div>", unsafe_allow_html=True)
        return sel_year, sel_month, agg_mode, years_all
    def render_metric_card(icon, title, main, sub="", color="#1f77b4"):
        st.markdown(f"""<div style="background-color:#ffffff;border-radius:22px;padding:24px;box-shadow:0 4px 18px rgba(0,0,0,0.06);height:100%;">
        <div style="font-size:44px;line-height:1;margin-bottom:8px;">{icon}</div>
        <div style="font-size:18px;font-weight:650;color:#444;margin-bottom:6px;">{title}</div>
        <div style="font-size:34px;font-weight:750;color:{color};margin-bottom:8px;">{main}</div>
        <div style="font-size:14px;color:#444;font-weight:500;">{sub}</div></div>""", unsafe_allow_html=True)
    def render_rate_donut(rate, color):
        if pd.isna(rate): return
        fig = go.Figure(data=[go.Pie(values=[min(rate, 200), max(100-rate, 0)], hole=0.7, marker=dict(colors=[color, "#e5e7eb"]), textinfo="none")])
        fig.update_layout(showlegend=False, width=240, height=240, margin=dict(t=0, b=0, l=0, r=0), annotations=[dict(text=f"{rate:.1f}%", x=0.5, y=0.5, showarrow=False, font=dict(size=20, color=color))])
        st.plotly_chart(fig, use_container_width=False)

    # Core Logic Functions
    def monthly_core_dashboard(long_df, unit_label, key_prefix=""):
        st.markdown("## 📌 월간 핵심 대시보드")
        sel_year, sel_month, agg_mode, years_all = render_section_selector(long_df, "월간 핵심 대시보드", key_prefix + "dash_base_")
        mode_tag = "당월" if agg_mode == "당월" else "연도누적"
        base_this = apply_period_filter(long_df, sel_year, sel_month, agg_mode)
        plan_total = base_this[base_this["계획/실적"] == "계획"]["값"].sum()
        act_total = base_this[base_this["계획/실적"] == "실적"]["값"].sum()
        
        prev_year = sel_year - 1
        base_prev = apply_period_filter(long_df, prev_year, sel_month, agg_mode) if prev_year in years_all else pd.DataFrame()
        prev_total = base_prev[base_prev["계획/실적"] == "실적"]["값"].sum() if not base_prev.empty else np.nan

        plan_diff = act_total - plan_total
        plan_rate = (act_total / plan_total * 100.0) if plan_total else np.nan
        prev_diff = act_total - prev_total
        prev_rate = (act_total / prev_total * 100.0) if prev_total else np.nan

        c1, c2, c3 = st.columns(3)
        with c1: render_metric_card("📘", f"계획 합계 ({unit_label})", fmt_num_safe(plan_total), color="#2563eb")
        with c2: render_metric_card("📗", f"실적 합계 ({unit_label})", fmt_num_safe(act_total), f"차이 {fmt_num_safe(plan_diff)} · 달성률 {fmt_rate(plan_rate)}", "#16a34a")
        with c3: render_metric_card("📙", f"전년 동월 실적 ({unit_label})", fmt_num_safe(prev_total), f"차이 {fmt_num_safe(prev_diff)} · 증감률 {fmt_rate(prev_rate)}", "#f97316")
        
        st.markdown("#### 🎯 달성률 요약")
        d1, d2, d3, d4, d5 = st.columns([1, 2, 1, 2, 1])
        with d2: render_rate_donut(plan_rate, "#16a34a"); st.caption("계획 달성률")
        with d4: render_rate_donut(prev_rate, "#f97316"); st.caption("전년 대비 증감률")

    def monthly_trend_section(long_df, unit_label, key_prefix=""):
        st.markdown("### 📈 월별 추이 그래프")
        sel_year, sel_month, agg_mode, years_all = render_section_selector(long_df, "월별 추이", key_prefix + "trend_", fixed_mode="연 누적", show_mode=False)
        sel_years = st.multiselect("연도 선택", years_all, default=[y for y in [2023, 2024, 2025] if y in years_all] or [sel_year], key=f"{key_prefix}trend_years")
        if not sel_years: return
        base = long_df[long_df["연"].isin(sel_years)].copy()
        base = apply_period_filter_multi_years(base, sel_month, agg_mode, sel_years)
        plot_df = base.groupby(["연", "월", "계획/실적"], as_index=False)["값"].sum()
        plot_df["라벨"] = plot_df["연"].astype(str) + "년 " + plot_df["계획/실적"]
        fig = px.line(plot_df, x="월", y="값", color="라벨", line_dash="계획/실적", markers=True)
        fig.update_layout(yaxis_title=f"판매량 ({unit_label})")
        st.plotly_chart(fig, use_container_width=True)

    def load_supply_sheets(excel_bytes):
        xls = pd.ExcelFile(io.BytesIO(excel_bytes), engine="openpyxl")
        return (xls.parse("월별계획_실적") if "월별계획_실적" in xls.sheet_names else pd.DataFrame(),
                xls.parse("일별실적") if "일별실적" in xls.sheet_names else pd.DataFrame())

    def clean_supply_month_df(df):
        df = _clean_base(df)
        df = df.dropna(subset=["연", "월"])
        return df

    def supply_core_dashboard(month_df, key_prefix=""):
        st.markdown("## 📌 월간 핵심 대시보드 (공급량)")
        plan_cols = [c for c in month_df.columns if c.startswith("계획(")]
        act_col = "실적_공급량(MJ)"
        if month_df.empty or act_col not in month_df.columns: return None
        plan_choice = st.radio("계획 기준", plan_cols, index=0, horizontal=True, key=f"{key_prefix}pc")
        
        long_dummy = month_df[["연", "월"]].copy()
        long_dummy["계획/실적"], long_dummy["값"] = "실적", pd.to_numeric(month_df[act_col], errors="coerce")
        sel_year, sel_month, agg_mode, years_all = render_section_selector(long_dummy.dropna(), "월간 핵심", key_prefix + "dash_")
        
        this_period = apply_period_filter(month_df, sel_year, sel_month, agg_mode)
        plan_val = this_period[plan_choice].sum() / 1000.0
        act_val = this_period[act_col].sum() / 1000.0
        
        c1, c2 = st.columns(2)
        with c1: render_metric_card("📘", "계획 (GJ)", fmt_num_safe(plan_val))
        with c2: render_metric_card("📗", "실적 (GJ)", fmt_num_safe(act_val), f"달성률 {fmt_rate(act_val/plan_val*100) if plan_val else '-'}")
        return sel_year, sel_month, agg_mode, plan_choice

    def supply_monthly_trend(month_df, plan_choice, sel_month, key_prefix=""):
        st.markdown("### 📈 월별 추이 (공급량)")
        years = sorted(month_df["연"].unique())
        sel_years = st.multiselect("연도 선택", years, default=[y for y in [2023, 2024, 2025] if y in years], key=f"{key_prefix}trend_y")
        if not sel_years: return
        base = month_df[month_df["연"].isin(sel_years)].copy()
        base = base[base["월"] <= sel_month]
        vals = np.column_stack([base["실적_공급량(MJ)"].values, base[plan_choice].values]) / 1000.0
        plot_df = pd.DataFrame({"연": np.repeat(base["연"].values, 2), "월": np.repeat(base["월"].values, 2), 
                                "구분": ["실적", "계획"] * len(base), "값": np.ravel(vals)})
        plot_df["라벨"] = plot_df["연"].astype(str) + "년 " + plot_df["구분"]
        fig = px.line(plot_df, x="월", y="값", color="라벨", line_dash="구분", markers=True)
        st.plotly_chart(fig, use_container_width=True)

    # --- Analysis Tab Main Logic ---
    st.sidebar.markdown("---")
    st.sidebar.header("📌 공급량 분석 메뉴")
    sub_menu = st.sidebar.radio("분석 항목", ["판매량 분석", "공급량 분석(월)", "공급량 분석(일)"], key="sub_menu")

    st.sidebar.header("📂 데이터 파일 (분석용)")
    
    # 1. 판매량 분석
    if sub_menu == "판매량 분석":
        src = st.sidebar.radio("데이터 소스", ["레포 파일", "업로드"], key="s_src")
        excel_bytes = None
        if src == "업로드":
            up = st.sidebar.file_uploader("판매량 엑셀", type=["xlsx"], key="s_up")
            if up: excel_bytes = up.getvalue()
        else:
            path = Path(__file__).parent / DEFAULT_SALES_XLSX
            if path.exists(): excel_bytes = path.read_bytes()
            else: st.sidebar.warning(f"{DEFAULT_SALES_XLSX} 없음")
            
        if excel_bytes:
            st.markdown("## 1) 판매량 계획 / 실적 분석")
            sheets = load_all_sheets(excel_bytes)
            long_dict = build_long_dict(sheets)
            if "열량" in long_dict:
                df = long_dict["열량"].copy()
                df["값"] /= 1000.0
                monthly_core_dashboard(df, "GJ", "sales_")
                monthly_trend_section(df, "GJ", "sales_tr_")
            else:
                st.info("판매량(열량) 데이터를 찾을 수 없습니다.")

    # 2. 공급량 분석 (월/일)
    else:
        src = st.sidebar.radio("데이터 소스", ["레포 파일", "업로드"], key="sp_src")
        supply_bytes = None
        if src == "업로드":
            up = st.sidebar.file_uploader("공급량 엑셀", type=["xlsx"], key="sp_up")
            if up: supply_bytes = up.getvalue()
        else:
            path = Path(__file__).parent / DEFAULT_SUPPLY_XLSX
            if path.exists(): supply_bytes = path.read_bytes()
            else: st.sidebar.warning(f"{DEFAULT_SUPPLY_XLSX} 없음")

        if supply_bytes:
            month_df, day_df = load_supply_sheets(supply_bytes)
            month_df = clean_supply_month_df(month_df)
            
            if sub_menu == "공급량 분석(월)":
                res = supply_core_dashboard(month_df, "sp_m_")
                if res:
                    _, sel_month, _, plan_choice = res
                    st.markdown("---")
                    supply_monthly_trend(month_df, plan_choice, sel_month, "sp_m_tr_")
            else:
                st.markdown("## 3) 공급량 분석(일)")
                st.info("일별 분석 기능은 일별실적 시트가 필요합니다.")
                # (형님이 주신 코드의 일별 분석 로직을 여기에 확장 가능)
                if not day_df.empty:
                    st.dataframe(day_df.head())


# ─────────────────────────────────────────────────────────
# [메인 실행부] 사이드바 네비게이션
# ─────────────────────────────────────────────────────────
st.sidebar.title("통합 메뉴")
menu = st.sidebar.radio("이동", ["도시가스 공급실적 관리", "공급량 분석"])

if menu == "도시가스 공급실적 관리":
    app_performance_management()
else:
    app_supply_analysis()
