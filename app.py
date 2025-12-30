import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="도시가스 공급실적 대시보드", layout="wide")

def load_data(file_source):
    # 1. 일단 엑셀을 헤더 없이 통째로 읽습니다.
    try:
        raw_df = pd.read_excel(file_source, sheet_name='연간', header=None)
    except:
        raw_df = pd.read_excel(file_source, sheet_name=0, header=None)

    # 2. '날짜'라는 글자가 들어있는 행을 무조건 찾아냅니다.
    header_idx = None
    for i, row in raw_df.iterrows():
        # 행의 값 중 '날짜'라는 글자가 포함되어 있으면 그곳이 제목줄입니다.
        if row.astype(str).str.contains('날짜').any():
            header_idx = i
            break
    
    if header_idx is None:
        st.error("❌ 엑셀 시트에서 '날짜' 컬럼 제목을 찾을 수 없습니다. 시트 이름을 확인해주세요.")
        st.stop()

    # 3. 데이터 본체 추출 및 컬럼명 정리
    df = raw_df.iloc[header_idx+1:].copy()
    headers = raw_df.iloc[header_idx].astype(str).str.strip().tolist()
    df.columns = headers

    # 4. 컬럼명 매칭 (이름이 정확하지 않아도 위치와 단어로 찾기)
    col_map = {}
    for i, col in enumerate(df.columns):
        if '날짜' in col: col_map['date'] = col
        elif '계획' in col and 'GJ' in col: col_map['p_gj'] = col
        elif '실적' in col and 'GJ' in col: col_map['a_gj'] = col
        elif '실적' in col and 'm3' in col: col_map['a_m3'] = col

    # 5. 데이터 형식 강제 변환 (에러 방지의 핵심)
    df['date_dt'] = pd.to_datetime(df[col_map['date']], errors='coerce')
    df = df.dropna(subset=['date_dt']) # 날짜 없는 줄 삭제
    
    for key in ['p_gj', 'a_gj', 'a_m3']:
        if key in col_map:
            df[key] = pd.to_numeric(df[col_map[key]], errors='coerce').fillna(0)
        else:
            df[key] = 0 # 컬럼 못찾으면 0으로 생성
            
    return df

# 파일 로딩 섹션
st.sidebar.header("📂 데이터 관리")
uploaded_file = st.sidebar.file_uploader("엑셀 파일 직접 업로드", type=["xlsx"])
DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

try:
    if uploaded_file:
        df = load_data(uploaded_file)
        st.sidebar.success("✅ 업로드 파일 적용 완료")
    else:
        df = load_data(DEFAULT_FILE)
        st.sidebar.info("ℹ️ GitHub 기본 데이터 로드")
except Exception as e:
    st.error(f"⚠️ 데이터 로드 실패: {e}")
    st.info("파일 이름과 시트 이름('연간')을 다시 확인해주세요.")
    st.stop()

# 화면 구성
st.title("📊 도시가스 실적 대시보드 (Han형님 전용)")
selected_date = st.date_input("조회 기준일 선택", value=df['date_dt'].min())
target_date = pd.to_datetime(selected_date)

# 6. 진도율 계산 로직
def get_metrics(df, t_date):
    ytd = df[df['date_dt'] <= t_date]
    mtd = df[(df['date_dt'] <= t_date) & (df['date_dt'].dt.month == t_date.month)]
    day = df[df['date_dt'] == t_date]
    
    res = {}
    for label, d in zip(['일간', '월간누계', '연간누계'], [day, mtd, ytd]):
        p = d['p_gj'].sum()
        a = d['a_gj'].sum()
        # 천 m3 환산
        m3 = d['a_m3'].sum() / 1000 
        # 0으로 나누기 방지
        ach = (a / p * 100) if p > 0 else 0
        res[label] = {'p': p, 'a': a, 'm3': m3, 'ach': ach}
    return res

m = get_metrics(df, target_date)

# 7. 메트릭 레이아웃
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("오늘 실적 (GJ)", f"{m['일간']['a']:,.0f}", f"{m['일간']['ach']-100:.1f}%")
    st.caption(f"당일 계획: {m['일간']['p']:,.0f} GJ")
with c2:
    st.metric("월간 진도율 (MTD)", f"{m['월간누계']['ach']:.1f}%", f"{m['월간누계']['a'] - m['월간누계']['p']:,.0f} GJ")
    st.write(f"누적 실적: {m['월간누계']['m3']:,.1f} (천 m3)")
with c3:
    st.metric("연간 진도율 (YTD)", f"{m['연간누계']['ach']:.1f}%")
    st.write(f"누적 계획: {m['연간누계']['p']:,.0f} GJ")

st.divider()
st.subheader("📋 선택일 상세 데이터")
st.dataframe(df[df['date_dt'] == target_date], use_container_width=True)
