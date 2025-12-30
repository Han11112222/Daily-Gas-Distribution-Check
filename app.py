import streamlit as st
import pandas as pd

st.set_page_config(page_title="도시가스 공급실적 대시보드", layout="wide")

def load_data(file_source):
    # 1. 일단 시트를 읽어옵니다.
    try:
        raw_df = pd.read_excel(file_source, sheet_name='연간', header=None)
    except:
        raw_df = pd.read_excel(file_source, sheet_name=0, header=None)

    # 2. '날짜'라는 단어가 포함된 행을 찾아 헤더로 설정
    header_idx = 0
    for i, row in raw_df.iterrows():
        if row.astype(str).str.contains('날짜').any():
            header_idx = i
            break
            
    df = raw_df.iloc[header_idx+1:].copy()
    df.columns = raw_df.iloc[header_idx].values
    df.columns = [str(c).strip() for c in df.columns]

    # 3. [핵심] 컬럼명을 유연하게 매칭 (이름이 정확하지 않아도 찾음)
    col_map = {}
    for col in df.columns:
        if '날짜' in col: col_map['날짜'] = col
        elif '계획' in col and 'GJ' in col: col_map['p_gj'] = col
        elif '실적' in col and 'GJ' in col: col_map['a_gj'] = col
        elif '계획' in col and 'm3' in col: col_map['p_m3'] = col
        elif '실적' in col and 'm3' in col: col_map['a_m3'] = col

    # 필수 컬럼 체크
    if '날짜' not in col_map:
        st.error(f"❌ '날짜' 컬럼을 찾을 수 없습니다. 현재 확인된 컬럼: {list(df.columns)}")
        st.stop()

    # 4. 데이터 정제
    df['날짜'] = pd.to_datetime(df[col_map['날짜']], errors='coerce')
    df = df.dropna(subset=['날짜'])
    
    for key, col_name in col_map.items():
        if key != '날짜':
            df[key] = pd.to_numeric(df[col_name], errors='coerce').fillna(0)
    
    return df, col_map

# 파일 로딩
st.sidebar.header("📊 데이터 설정")
uploaded_file = st.sidebar.file_uploader("엑셀 파일 업로드 (선택)", type=["xlsx"])
DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

try:
    if uploaded_file:
        df, col_map = load_data(uploaded_file)
        st.sidebar.success("✅ 업로드 파일 적용")
    else:
        df, col_map = load_data(DEFAULT_FILE)
        st.sidebar.info("ℹ️ 기본 파일 사용 중")
except Exception as e:
    st.error(f"⚠️ 로드 실패: {e}")
    st.stop()

# 5. UI 및 계산
st.title("🔥 도시가스 공급계획 대비 실적 분석")
selected_date = st.date_input("조회 기준일을 선택하세요", value=df['날짜'].min())
t_date = pd.to_datetime(selected_date)

def get_summary(df, target):
    ytd = df[df['날짜'] <= target]
    mtd = df[(df['날짜'] <= target) & (df['날짜'].dt.month == target.month)]
    day = df[df['날짜'] == target]
    
    res = {}
    for label, d in zip(['일간', '월간누계', '연간누계'], [day, mtd, ytd]):
        p = d['p_gj'].sum()
        a = d['a_gj'].sum()
        a_m3 = d['a_m3'].sum() / 1000
        ach = (a / p * 100) if p != 0 else 0
        res[label] = {'p': p, 'a': a, 'm3': a_m3, 'ach': ach}
    return res

metrics = get_summary(df, t_date)

# 6. 메트릭 출력
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("오늘 실적 (GJ)", f"{metrics['일간']['a']:,.0f}", f"{metrics['일간']['ach']-100:.1f}%")
    st.caption(f"당일 계획: {metrics['일간']['p']:,.0f} GJ")
with c2:
    st.metric("월간 진도율 (MTD)", f"{metrics['월간누계']['ach']:.1f}%", f"{metrics['월간누계']['a'] - metrics['월간누계']['p']:,.0f} GJ")
    st.write(f"실적: {metrics['월간누계']['m3']:,.1f} (천 m3)")
with c3:
    st.metric("연간 진도율 (YTD)", f"{metrics['연간누계']['ach']:.1f}%")
    st.write(f"누계 계획: {metrics['연간누계']['p']:,.0f} GJ")

st.divider()
with st.expander("🔍 데이터 디버깅 정보 (문제가 있을 때만 확인하세요)"):
    st.write("인식된 컬럼 맵핑:", col_map)
    st.write("데이터 샘플:", df.head())
