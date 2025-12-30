import streamlit as st
import pandas as pd
import io

# 1. 화면 설정 (맨 윗줄에 있어야 함)
st.set_page_config(page_title="도시가스 공급실적 관리", layout="wide")

# --- 데이터 로드 및 전처리 함수 ---
def load_excel(file):
    try:
        # 헤더 없이 읽어서 구조 파악
        raw = pd.read_excel(file, sheet_name='연간', header=None)
    except:
        raw = pd.read_excel(file, sheet_name=0, header=None)

    # '연', '월', '일'이 있는 행 찾기 (헤더 자동 탐색)
    header_idx = None
    for i, row in raw.iterrows():
        vals = row.astype(str).values
        if '연' in vals and '월' in vals and '일' in vals:
            header_idx = i
            break
            
    if header_idx is None:
        return None, "❌ [연, 월, 일] 컬럼을 찾을 수 없습니다."

    # 데이터 본문 추출
    df = raw.iloc[header_idx+1:].copy()
    # 컬럼명 공백 제거
    df.columns = raw.iloc[header_idx].astype(str).str.replace(r'\s+', '', regex=True).tolist()

    # [핵심] 컬럼 매칭 (예상공급량 vs 계획 등 용어 차이 대응)
    col_map = {}
    for c in df.columns:
        if '연' in c: col_map['y'] = c
        elif '월' in c: col_map['m'] = c
        elif '일' in c: col_map['d'] = c
        # 계획(예상) GJ 찾기 ('계획' 또는 '예상' 단어 포함 시)
        elif ('계획' in c or '예상' in c) and 'GJ' in c: col_map['p_gj'] = c
        # 실적 GJ 찾기
        elif '실적' in c and 'GJ' in c: col_map['a_gj'] = c
        # 실적 m3 찾기
        elif '실적' in c and 'm3' in c: col_map['a_m3'] = c

    # 데이터 변환
    try:
        # 날짜 생성
        df['날짜'] = pd.to_datetime({
            'year': pd.to_numeric(df[col_map['y']], errors='coerce'),
            'month': pd.to_numeric(df[col_map['m']], errors='coerce'),
            'day': pd.to_numeric(df[col_map['d']], errors='coerce')
        }, errors='coerce')
        df = df.dropna(subset=['날짜'])

        # 표준 컬럼명으로 데이터 정리 (숫자로 변환)
        # '예상공급량(GJ)' 같은 이름도 '계획(GJ)'라는 표준 이름으로 저장해서 관리
        df['계획(GJ)'] = pd.to_numeric(df[col_map.get('p_gj')], errors='coerce').fillna(0)
        df['실적(GJ)'] = pd.to_numeric(df[col_map.get('a_gj')], errors='coerce').fillna(0)
        df['실적(m3)'] = pd.to_numeric(df[col_map.get('a_m3')], errors='coerce').fillna(0)
        
        # 필요한 컬럼만 남김
        df = df[['날짜', '계획(GJ)', '실적(GJ)', '실적(m3)']]
        
    except Exception as e:
        return None, f"❌ 데이터 변환 오류: {e}"

    return df, None

# --- 세션 상태 관리 (입력 데이터 유지) ---
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
    else:
        st.error(err)
elif st.session_state.data is None:
    try:
        df, err = load_excel(DEFAULT_FILE)
        if not err: 
            st.session_state.data = df
            st.sidebar.info("ℹ️ 기본 파일 로드됨")
    except:
        st.warning("기본 파일을 찾을 수 없습니다.")

if st.session_state.data is None:
    st.stop()

# 작업용 데이터프레임
df = st.session_state.data

# --- 메인 UI ---
st.title("🔥 도시가스 공급실적 관리")

# 1. 날짜 선택 (요청하신 대로 작게!)
col_date, col_space = st.columns([1, 5])
with col_date:
    selected_date = st.date_input(
        "조회 기준일", 
        value=df['날짜'].min(), 
        label_visibility="collapsed"
    )
target_date = pd.to_datetime(selected_date)

# 2. 진도율 계산 (형님의 '기간 매칭' 로직 적용)
def calc_kpi(data, t):
    # 필터 조건
    mask_day = data['날짜'] == t
    # 월간: 1일 ~ 선택일 (월 전체 아님!)
    mask_mtd = (data['날짜'] <= t) & (data['날짜'].dt.month == t.month) & (data['날짜'].dt.year == t.year)
    # 연간: 1월 1일 ~ 선택일 (연 전체 아님!)
    mask_ytd = (data['날짜'] <= t) & (data['날짜'].dt.year == t.year)
    
    res = {}
    for label, mask in zip(['Day', 'MTD', 'YTD'], [mask_day, mask_mtd, mask_ytd]):
        d = data[mask]
        p = d['계획(GJ)'].sum()
        a = d['실적(GJ)'].sum()
        m3 = d['실적(m3)'].sum() / 1000 # 천 단위
        rate = (a / p * 100) if p > 0 else 0
        res[label] = {'p': p, 'a': a, 'm3': m3, 'rate': rate}
    return res

metrics = calc_kpi(df, target_date)

# 3. 지표 출력
st.markdown("---")
c1, c2, c3 = st.columns(3)

with c1:
    st.metric(
        label=f"일간 실적 ({target_date.strftime('%m.%d')})",
        value=f"{metrics['Day']['a']:,.0f} GJ",
        delta=f"{metrics['Day']['rate']-100:.1f}%"
    )
    st.caption(f"🎯 당일 계획: {metrics['Day']['p']:,.0f} GJ")

with c2:
    st.metric(
        label="월간 누적 진도율 (MTD)",
        value=f"{metrics['MTD']['rate']:.1f}%",
        delta=f"{metrics['MTD']['a'] - metrics['MTD']['p']:,.0f} GJ"
    )
    st.caption(f"🔥 누적 계획: {metrics['MTD']['p']:,.0f} GJ")
    st.text(f"💧 실적(부피): {metrics['MTD']['m3']:,.1f} 천 m³")

with c3:
    st.metric(
        label="연간 누적 진도율 (YTD)",
        value=f"{metrics['YTD']['rate']:.1f}%",
        delta=f"{metrics['YTD']['a'] - metrics['YTD']['p']:,.0f} GJ"
    )
    st.caption(f"🔥 누적 계획: {metrics['YTD']['p']:,.0f} GJ")

st.markdown("---")

# 4. [핵심] 데이터 입력 테이블
st.subheader(f"📝 실적 입력 ({target_date.month}월)")
st.info("아래 표의 '실적' 칸을 클릭해 수정하고 엔터를 치면, 위 그래프가 즉시 반영됩니다.")

# 해당 월 데이터만 필터링해서 보여주기
mask_month = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month)
view_df = df.loc[mask_month].copy()

# 데이터 에디터 (수정 기능)
edited_df = st.data_editor(
    view_df,
    column_config={
        "날짜": st.column_config.DateColumn("공급일자", format="YYYY-MM-DD", disabled=True),
        "계획(GJ)": st.column_config.NumberColumn("계획(GJ)", format="%d", disabled=True),
        "실적(GJ)": st.column_config.NumberColumn("실적(GJ) ✏️", format="%d"),
        "실적(m3)": st.column_config.NumberColumn("실적(m3) ✏️", format="%d"),
    },
    hide_index=True,
    use_container_width=True
)

# 5. 수정 사항 반영 로직
if not edited_df.equals(view_df):
    # 수정된 부분만 원본 df에 업데이트
    df.update(edited_df)
    st.session_state.data = df
    st.rerun()
