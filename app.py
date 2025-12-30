import streamlit as st
import pandas as pd
import io

# 1. 화면 설정 (맨 윗줄 필수)
st.set_page_config(page_title="도시가스 공급실적 관리", layout="wide")

# --- 내부 함수: 엑셀 읽기 및 전처리 ---
def load_excel(file):
    try:
        raw = pd.read_excel(file, sheet_name='연간', header=None)
    except:
        try:
            raw = pd.read_excel(file, sheet_name=0, header=None)
        except Exception as e:
            return None, f"❌ 파일 읽기 실패: {e}"

    # '연', '월', '일'이 있는 행(Header) 찾기
    header_idx = None
    for i, row in raw.iterrows():
        vals = row.astype(str).values
        if '연' in vals and '월' in vals and '일' in vals:
            header_idx = i
            break
            
    if header_idx is None:
        return None, "❌ [연, 월, 일] 컬럼을 찾을 수 없습니다. 파일 양식을 확인해주세요."

    # 데이터 추출 및 컬럼명 정리
    df = raw.iloc[header_idx+1:].copy()
    # 공백 제거 (예: '계획 (GJ)' -> '계획(GJ)')
    df.columns = raw.iloc[header_idx].astype(str).str.replace(r'\s+', '', regex=True).tolist()

    # 컬럼 매칭 (이름이 조금 달라도 단어로 찾기)
    col_map = {}
    for c in df.columns:
        if '연' in c: col_map['y'] = c
        elif '월' in c: col_map['m'] = c
        elif '일' in c: col_map['d'] = c
        # 계획/예상 모두 대응
        elif ('계획' in c or '예상' in c) and 'GJ' in c: col_map['p_gj'] = c
        elif '실적' in c and 'GJ' in c: col_map['a_gj'] = c
        elif ('계획' in c or '예상' in c) and 'm3' in c: col_map['p_m3'] = c
        elif '실적' in c and 'm3' in c: col_map['a_m3'] = c

    # 데이터 변환 (날짜 생성 및 숫자 강제 변환)
    try:
        df['날짜'] = pd.to_datetime({
            'year': pd.to_numeric(df[col_map['y']], errors='coerce'),
            'month': pd.to_numeric(df[col_map['m']], errors='coerce'),
            'day': pd.to_numeric(df[col_map['d']], errors='coerce')
        }, errors='coerce')
        df = df.dropna(subset=['날짜'])

        # 표준 컬럼 생성 (숫자로 변환, NaN은 0으로)
        df['계획(GJ)'] = pd.to_numeric(df[col_map.get('p_gj')], errors='coerce').fillna(0)
        df['실적(GJ)'] = pd.to_numeric(df[col_map.get('a_gj')], errors='coerce').fillna(0)
        df['계획(m3)'] = pd.to_numeric(df[col_map.get('p_m3')], errors='coerce').fillna(0)
        df['실적(m3)'] = pd.to_numeric(df[col_map.get('a_m3')], errors='coerce').fillna(0)
        
        # 필요한 컬럼만 선택하여 깔끔하게 정리
        df = df[['날짜', '계획(GJ)', '실적(GJ)', '계획(m3)', '실적(m3)']]
        
    except Exception as e:
        return None, f"❌ 데이터 변환 오류: {e}"

    return df, None

# --- 세션 상태 (데이터 유지용) ---
if 'data' not in st.session_state:
    st.session_state.data = None

# 사이드바: 파일 관리
st.sidebar.header("📂 데이터 파일")
uploaded = st.sidebar.file_uploader("엑셀 파일 업로드 (초기화)", type=['xlsx'])
DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

# 파일 로드 로직
if uploaded:
    df, err = load_excel(uploaded)
    if not err: 
        st.session_state.data = df
        st.sidebar.success("✅ 파일 로드 성공")
    else: st.error(err)
elif st.session_state.data is None:
    try:
        df, err = load_excel(DEFAULT_FILE)
        if not err: 
            st.session_state.data = df
            st.sidebar.info("ℹ️ 기본 파일 사용 중")
    except:
        st.warning("기본 파일을 찾을 수 없습니다.")

if st.session_state.data is None:
    st.stop()

# 메인 데이터프레임 할당
df = st.session_state.data

# --- 메인 화면 UI ---
st.title("🔥 도시가스 공급실적 관리")

# 1. 날짜 선택 (컴팩트하게)
col_date, col_space = st.columns([1, 5])
with col_date:
    selected_date = st.date_input(
        "조회 기준일", 
        value=df['날짜'].min(), 
        label_visibility="collapsed"
    )
target_date = pd.to_datetime(selected_date)

# 2. KPI 계산 로직
def calc_kpi(data, t):
    # 필터: 일간 / 월간누계 / 연간누계
    mask_day = data['날짜'] == t
    mask_mtd = (data['날짜'] <= t) & (data['날짜'].dt.month == t.month) & (data['날짜'].dt.year == t.year)
    mask_ytd = (data['날짜'] <= t) & (data['날짜'].dt.year == t.year)
    
    res = {}
    for label, mask in zip(['Day', 'MTD', 'YTD'], [mask_day, mask_mtd, mask_ytd]):
        d = data[mask]
        
        # GJ 계산
        p_gj = d['계획(GJ)'].sum()
        a_gj = d['실적(GJ)'].sum()
        diff_gj = a_gj - p_gj
        rate_gj = (a_gj / p_gj * 100) if p_gj > 0 else 0
        
        # m3 계산 (천 단위로 변환)
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

# 3. 대시보드 출력

# --- 섹션 1: 열량 (GJ) ---
st.markdown("### 🔥 열량 실적 (GJ)")
col_g1, col_g2, col_g3 = st.columns(3)

# 일간 GJ
with col_g1:
    m = metrics['Day']['gj']
    st.metric(
        label=f"일간 달성률 {m['rate']:.1f}%", # 라벨에 달성률 표기
        value=f"{int(m['a']):,} GJ",          # 메인은 실적
        delta=f"{int(m['diff']):+,} GJ"        # 하단은 차이 (+/- 자동 붙음)
    )
    st.caption(f"계획: {int(m['p']):,} GJ")    # 참고용 계획

# 월간 GJ
with col_g2:
    m = metrics['MTD']['gj']
    st.metric(
        label=f"월간 누적 달성률 {m['rate']:.1f}%",
        value=f"{int(m['a']):,} GJ",
        delta=f"{int(m['diff']):+,} GJ"
    )
    st.caption(f"누적 계획: {int(m['p']):,} GJ")

# 연간 GJ
with col_g3:
    m = metrics['YTD']['gj']
    st.metric(
        label=f"연간 누적 달성률 {m['rate']:.1f}%",
        value=f"{int(m['a']):,} GJ",
        delta=f"{int(m['diff']):+,} GJ"
    )
    st.caption(f"누적 계획: {int(m['p']):,} GJ")

st.markdown("---")

# --- 섹션 2: 부피 (천 m³) ---
st.markdown("### 💧 부피 실적 (천 m³)")
col_m1, col_m2, col_m3 = st.columns(3)

# 일간 m3
with col_m1:
    m = metrics['Day']['m3']
    st.metric(
        label=f"일간 달성률 {m['rate']:.1f}%",
        value=f"{int(m['a']):,} (천 m³)",
        delta=f"{int(m['diff']):+,}"
    )
    st.caption(f"계획: {int(m['p']):,}")

# 월간 m3
with col_m2:
    m = metrics['MTD']['m3']
    st.metric(
        label=f"월간 누적 달성률 {m['rate']:.1f}%",
        value=f"{int(m['a']):,} (천 m³)",
        delta=f"{int(m['diff']):+,}"
    )
    st.caption(f"누적 계획: {int(m['p']):,}")

# 연간 m3
with col_m3:
    m = metrics['YTD']['m3']
    st.metric(
        label=f"연간 누적 달성률 {m['rate']:.1f}%",
        value=f"{int(m['a']):,} (천 m³)",
        delta=f"{int(m['diff']):+,}"
    )
    st.caption(f"누적 계획: {int(m['p']):,}")

st.markdown("---")

# --- 섹션 3: 데이터 입력 (분리형) ---
st.subheader(f"📝 {target_date.month}월 실적 입력")
st.info("💡 값을 수정하고 엔터(Enter)를 치면 상단 그래프가 즉시 업데이트됩니다.")

# 해당 월 데이터만 필터링
mask_month = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month)

# (1) 열량(GJ) 입력 테이블
st.markdown("##### 1️⃣ 열량(GJ) 입력")
view_gj = df.loc[mask_month, ['날짜', '계획(GJ)', '실적(GJ)']].copy()

edited_gj = st.data_editor(
    view_gj,
    column_config={
        "날짜": st.column_config.DateColumn("공급일자", format="YYYY-MM-DD", disabled=True),
        "계획(GJ)": st.column_config.NumberColumn("계획(GJ)", format="%d", disabled=True), # 수정 불가
        "실적(GJ)": st.column_config.NumberColumn("실적(GJ) ✏️", format="%d", min_value=0), # 수정 가능
    },
    hide_index=True,
    use_container_width=True,
    key="editor_gj"
)

# GJ 수정 반영
if not edited_gj.equals(view_gj):
    df.update(edited_gj)
    st.session_state.data = df
    st.rerun()

st.markdown("<br>", unsafe_allow_html=True) # 간격 띄우기

# (2) 부피(천 m3) 입력 테이블
st.markdown("##### 2️⃣ 부피(천 m³) 입력")
# 화면 표시용: 원본 m3 데이터를 1000으로 나누어 표시
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
    hide_index=True,
    use_container_width=True,
    key="editor_m3"
)

# m3 수정 반영 (입력값을 다시 1000 곱해서 원본에 저장)
if not edited_m3.equals(view_m3_display):
    new_raw_m3 = edited_m3['실적(천m3)'] * 1000
    df.loc[mask_month, '실적(m3)'] = new_raw_m3.values
    st.session_state.data = df
    st.rerun()

# 엑셀 다운로드 버튼
st.markdown("---")
buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
    df.to_excel(writer, sheet_name='연간', index=False)
    
st.download_button(
    label="💾 데이터 엑셀로 저장",
    data=buffer,
    file_name=f"실적데이터_{target_date.strftime('%Y%m%d')}.xlsx",
    mime="application/vnd.ms-excel"
)
