import streamlit as st
import pandas as pd

st.set_page_config(page_title="도시가스 공급실적 분석", layout="wide")

def load_data(file_source):
    # 1. '연간' 시트를 읽어오되, 제목 행 위치를 유동적으로 찾습니다.
    try:
        raw_df = pd.read_excel(file_source, sheet_name='연간', header=None)
    except:
        raw_df = pd.read_excel(file_source, sheet_name=0, header=None)

    # 2. '날짜'가 포함된 행을 찾아 헤더로 설정하는 로직
    header_idx = 0
    for i, row in raw_df.iterrows():
        if row.astype(str).str.contains('날짜').any():
            header_idx = i
            break
            
    df = raw_df.iloc[header_idx+1:].copy()
    df.columns = [str(c).strip() for c in raw_df.iloc[header_idx].values]

    # 3. 컬럼 맵핑 (이름이 조금 달라도 단어 포함 여부로 매칭)
    col_map = {}
    for col in df.columns:
        if '날짜' in col: col_map['date'] = col
        elif '계획' in col and 'GJ' in col: col_map['p_gj'] = col
        elif '실적' in col and 'GJ' in col: col_map['a_gj'] = col
        elif '계획' in col and 'm3' in col: col_map['p_m3'] = col
        elif '실적' in col and 'm3' in col: col_map['a_m3'] = col

    # 데이터 정제
    df['date_dt'] = pd.to_datetime(df[col_map['date']], errors='coerce')
    df = df.dropna(subset=['date_dt'])
    
    for key, col_name in col_map.items():
        if key != 'date':
            df[key] = pd.to_numeric(df[col_name], errors='coerce').fillna(0)
    
    return df

# 파일 로드
st.sidebar.header("📂 데이터 관리")
uploaded_file = st.sidebar.file_uploader("실적 엑셀 업로드", type=["xlsx"])
DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

try:
    if uploaded_file:
        df = load_data(uploaded_file)
        st.sidebar.success("✅ 업로드 파일 적용 중")
    else:
        df = load_data(DEFAULT_FILE)
        st.sidebar.info("ℹ️ GitHub 기본 파일 사용 중")
except Exception as e:
    st.error(f"⚠️ 에러 발생: {e}")
    st.stop()

# 화면 구성
st.title("📊 도시가스 공급실적 대시보드")
selected_date = st.date_input("조회 기준일 선택", value=df['date_dt'].min())
target = pd.to_datetime(selected_date)

# 4. 진도율 계산 (형님이 강조하신 '일대비 100%면 월대비 100%' 로직)
def get_metrics(df, target_date):
    # 선택일 기준 누적 데이터 필터링
    ytd = df[df['date_dt'] <= target_date]
    mtd = df[(df['date_dt'] <= target_date) & (df['date_dt'].dt.month == target_date.month)]
    day = df[df['date_dt'] == target_date]
    
    metrics = {}
    for label, d in zip(['일간', '월간누계', '연간누계'], [day, mtd, ytd]):
        p = d['p_gj'].sum()
        a = d['a_gj'].sum()
        a_m3 = d['a_m3'].sum() / 1000 # 천 m3 단위 환산
        ach = (a / p * 100) if p != 0 else 0
        metrics[label] = {'p': p, 'a': a, 'm3': a_m3, 'ach': ach}
    return metrics

m = get_metrics(df, target)

# 5. 지표 출력
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("오늘 실적 (GJ)", f"{m['일간']['a']:,.0f}", f"{m['일간']['ach']-100:.1f}%")
    st.caption(f"당일 계획: {m['일간']['p']:,.0f} GJ")
with c2:
    st.metric("월간 진도율 (MTD)", f"{m['월간누계']['ach']:.1f}%", f"{m['월간누계']['a'] - m['월간누계']['p']:,.0f} GJ")
    st.write(f"누적실적: {m['월간누계']['m3']:,.1f} (천 m3)")
with c3:
    st.metric("연간 진도율 (YTD)", f"{m['연간누계']['ach']:.1f}%")
    st.write(f"누계 계획: {m['연간누계']['p']:,.0f} GJ")

st.divider()
st.subheader("📋 상세 데이터")
st.dataframe(df[df['date_dt'] == target], use_container_width=True)
