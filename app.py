import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="도시가스 공급실적 분석", layout="wide")

def load_data(file_source):
    # 1. 엑셀을 헤더 없이 통째로 읽어옵니다.
    try:
        raw_df = pd.read_excel(file_source, sheet_name='연간', header=None)
    except:
        raw_df = pd.read_excel(file_source, sheet_name=0, header=None)

    # 2. '연', '월', '일'이 모두 포함된 행을 찾아 헤더(제목줄)로 잡습니다.
    header_idx = None
    for i, row in raw_df.iterrows():
        row_str = row.astype(str).values
        # 한 줄에 '연', '월', '일'이라는 글자가 모두 있으면 그게 제목줄입니다.
        if '연' in row_str and '월' in row_str and '일' in row_str:
            header_idx = i
            break
            
    if header_idx is None:
        st.error("❌ '연', '월', '일'로 구분된 제목 행을 찾을 수 없습니다. 파일을 확인해주세요.")
        st.stop()

    # 3. 데이터 본체 추출 및 컬럼명 정리
    df = raw_df.iloc[header_idx+1:].copy()
    headers = raw_df.iloc[header_idx].astype(str).str.replace(r'\s+', '', regex=True).tolist()
    df.columns = headers

    # 4. 컬럼 매칭 (연/월/일 + 계획/실적)
    col_map = {}
    for col in df.columns:
        if '연' in col and len(col) < 3: col_map['year'] = col
        elif '월' in col and len(col) < 3: col_map['month'] = col
        elif '일' in col and len(col) < 3: col_map['day'] = col
        elif '계획' in col and 'GJ' in col: col_map['p_gj'] = col
        elif '실적' in col and 'GJ' in col: col_map['a_gj'] = col
        elif '실적' in col and 'm3' in col: col_map['a_m3'] = col

    # 5. [핵심] 연+월+일 합쳐서 '날짜' 컬럼 생성
    try:
        # 숫자로 변환 (문자가 섞여있을 수 있으므로)
        y = pd.to_numeric(df[col_map['year']], errors='coerce')
        m = pd.to_numeric(df[col_map['month']], errors='coerce')
        d = pd.to_numeric(df[col_map['day']], errors='coerce')
        
        # 날짜 생성 (NaT 방지)
        df['날짜'] = pd.to_datetime({'year': y, 'month': m, 'day': d}, errors='coerce')
        df = df.dropna(subset=['날짜']) # 날짜가 안 만들어진 행(빈 행 등) 삭제
    except Exception as e:
        st.error(f"❌ 날짜 생성 중 오류 발생: {e}")
        st.stop()

    # 6. 숫자 데이터 변환 (계획, 실적)
    for key in ['p_gj', 'a_gj', 'a_m3']:
        if key in col_map:
            df[key] = pd.to_numeric(df[col_map[key]], errors='coerce').fillna(0)
        else:
            df[key] = 0
            
    return df

# --- 메인 실행 로직 ---
st.title("🔥 도시가스 공급실적 대시보드")

# 사이드바: 파일 업로드
st.sidebar.header("📂 데이터 파일")
uploaded_file = st.sidebar.file_uploader("엑셀 파일 업로드", type=["xlsx"])
DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

try:
    if uploaded_file:
        df = load_data(uploaded_file)
        st.sidebar.success("✅ 파일 적용 완료")
    else:
        df = load_data(DEFAULT_FILE)
        st.sidebar.info("ℹ️ 기본 데이터 사용 중")
except Exception as e:
    st.error(f"⚠️ 처리 중 오류가 발생했습니다: {e}")
    st.stop()

# 날짜 선택
selected_date = st.date_input("조회 기준일 선택", value=df['날짜'].min())
target_date = pd.to_datetime(selected_date)

# 계산 로직 (누적 계획 vs 누적 실적)
def calculate_metrics(df, t_date):
    day = df[df['날짜'] == t_date]
    mtd = df[(df['날짜'] <= t_date) & (df['날짜'].dt.month == t_date.month) & (df['날짜'].dt.year == t_date.year)]
    ytd = df[(df['날짜'] <= t_date) & (df['날짜'].dt.year == t_date.year)]
    
    res = {}
    for label, d in zip(['일간', '월간', '연간'], [day, mtd, ytd]):
        p = d['p_gj'].sum()
        a = d['a_gj'].sum()
        m3 = d['a_m3'].sum() / 1000 # 천 m3
        rate = (a / p * 100) if p > 0 else 0
        res[label] = {'p': p, 'a': a, 'm3': m3, 'rate': rate}
    return res

metrics = calculate_metrics(df, target_date)

# 결과 카드 출력
col1, col2, col3 = st.columns(3)

with col1: # 일간
    st.metric("오늘 실적 (GJ)", f"{metrics['일간']['a']:,.0f}", f"{metrics['일간']['rate']-100:.1f}%")
    st.caption(f"계획: {metrics['일간']['p']:,.0f} GJ")

with col2: # 월간 누계
    st.metric("월간 진도율 (MTD)", f"{metrics['월간']['rate']:.1f}%", f"{metrics['월간']['a'] - metrics['월간']['p']:,.0f} GJ")
    st.write(f"실적: {metrics['월간']['m3']:,.1f} (천 m3)")

with col3: # 연간 누계
    st.metric("연간 진도율 (YTD)", f"{metrics['연간']['rate']:.1f}%")
    st.write(f"계획: {metrics['연간']['p']:,.0f} GJ")

st.divider()
st.subheader("📋 상세 데이터 확인")
st.dataframe(df[df['날짜'] == target_date], use_container_width=True)
