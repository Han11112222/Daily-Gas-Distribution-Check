import streamlit as st
import pandas as pd
import re

st.set_page_config(page_title="도시가스 공급실적 분석", layout="wide")

def clean_col(name):
    """컬럼명에서 공백, 줄바꿈, 특수문자를 제거하여 순수 글자만 남깁니다."""
    return re.sub(r'[^a-zA-Z0-9가-힣]', '', str(name))

def load_data(file_source):
    # 1. 엑셀 로드 (헤더 없이 읽어서 진짜 시작점을 찾습니다)
    try:
        raw = pd.read_excel(file_source, sheet_name='연간', header=None)
    except:
        raw = pd.read_excel(file_source, sheet_name=0, header=None)

    # 2. '날짜'라는 글자가 들어있는 행을 찾습니다.
    header_idx = None
    for i, row in raw.iterrows():
        if row.astype(str).str.contains('날짜').any():
            header_idx = i
            break
            
    if header_idx is None:
        st.error("❌ '연간' 시트에서 '날짜' 제목을 찾을 수 없습니다. 시트 이름을 확인해주세요.")
        st.stop()

    # 3. 데이터 추출 및 컬럼명 정제
    df = raw.iloc[header_idx+1:].copy()
    raw_cols = raw.iloc[header_idx].values
    # 모든 컬럼명에서 공백/특수문자 제거 (예: '계획 (GJ)' -> '계획GJ')
    clean_cols = [clean_col(c) for c in raw_cols]
    df.columns = clean_cols

    # 4. 유연한 컬럼 매칭 (글자 일부만 맞으면 가져옵니다)
    col_map = {}
    for i, c in enumerate(clean_cols):
        if '날짜' in c: col_map['date'] = i
        elif '계획' in c and 'GJ' in c: col_map['p_gj'] = i
        elif '실적' in c and 'GJ' in c: col_map['a_gj'] = i
        elif '실적' in c and 'm3' in c: col_map['a_m3'] = i

    # 5. 데이터 타입 강제 변환
    final_df = pd.DataFrame()
    final_df['날짜'] = pd.to_datetime(df.iloc[:, col_map['date']], errors='coerce')
    final_df = final_df.dropna(subset=['날짜']) # 날짜 없는 행 제거
    
    # 해당 날짜에 맞는 다른 데이터들 붙이기
    final_df['p_gj'] = pd.to_numeric(df.iloc[:, col_map['p_gj']], errors='coerce').fillna(0)
    final_df['a_gj'] = pd.to_numeric(df.iloc[:, col_map['a_gj']], errors='coerce').fillna(0)
    final_df['a_m3'] = pd.to_numeric(df.iloc[:, col_map['a_m3']], errors='coerce').fillna(0)
    
    return final_df

# 파일 로딩
st.sidebar.header("📂 데이터 설정")
uploaded_file = st.sidebar.file_uploader("엑셀 파일 직접 업로드", type=["xlsx"])
DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

try:
    df = load_data(uploaded_file if uploaded_file else DEFAULT_FILE)
    if uploaded_file: st.sidebar.success("✅ 업로드 파일 적용")
    else: st.sidebar.info("ℹ️ GitHub 기본 파일 사용")
except Exception as e:
    st.error(f"⚠️ 파일 로드 중 심각한 에러: {e}")
    st.stop()

# 화면 구성 및 계산
st.title("🔥 도시가스 공급계획 대비 실적 분석")
selected_date = st.date_input("조회 기준일 선택", value=df['날짜'].min())
target = pd.to_datetime(selected_date)

# 6. 진도율 계산 (형님의 '일대비 100%면 월대비 100%' 로직)
def get_metrics(df, t):
    # 당일 / 당월누적 / 당해누적 필터
    day_df = df[df['날짜'] == t]
    mtd_df = df[(df['날짜'] <= t) & (df['날짜'].dt.month == t.month) & (df['날짜'].dt.year == t.year)]
    ytd_df = df[(df['날짜'] <= t) & (df['날짜'].dt.year == t.year)]
    
    res = {}
    for label, d in zip(['일간', '월간누계', '연간누계'], [day_df, mtd_df, ytd_df]):
        p = d['p_gj'].sum()
        a = d['a_gj'].sum()
        m3 = d['a_m3'].sum() / 1000 # 천 m3 환산
        ach = (a / p * 100) if p > 0 else 0
        res[label] = {'p': p, 'a': a, 'm3': m3, 'ach': ach}
    return res

m = get_metrics(df, target)

# 7. 메트릭 출력
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("오늘 실적 (GJ)", f"{m['일간']['a']:,.0f}", f"{m['일간']['ach']-100:.1f}%")
    st.caption(f"당일 계획: {m['일간']['p']:,.0f} GJ")
with c2:
    st.metric("월간 진도율 (MTD)", f"{m['월간누계']['ach']:.1f}%", f"{m['월간누계']['a'] - m['월간누계']['p']:,.0f} GJ")
    st.write(f"누적실적: {m['월간누계']['m3']:,.1f} (천 m3)")
with c3:
    st.metric("연간 진도율 (YTD)", f"{m['연간누계']['ach']:.1f}%")
    st.write(f"누적계획: {m['연간누계']['p']:,.0f} GJ")

st.divider()
st.subheader("📋 상세 데이터 (선택일)")
st.table(df[df['날짜'] == target])
