import streamlit as st
import pandas as pd
import io

# 1. 페이지 설정 (넓은 화면 사용)
st.set_page_config(page_title="도시가스 실적 관리", layout="wide")

# --- 데이터 로드 및 전처리 함수 ---
def process_excel(file):
    try:
        # 헤더 없이 읽어서 '연', '월', '일'이 있는 행 찾기
        raw = pd.read_excel(file, sheet_name='연간', header=None)
    except:
        raw = pd.read_excel(file, sheet_name=0, header=None)

    header_idx = None
    for i, row in raw.iterrows():
        r = row.astype(str).values
        if '연' in r and '월' in r and '일' in r:
            header_idx = i
            break
            
    if header_idx is None:
        return None, "❌ '연', '월', '일' 컬럼을 찾을 수 없습니다."

    # 데이터 본체 추출
    df = raw.iloc[header_idx+1:].copy()
    headers = raw.iloc[header_idx].astype(str).str.replace(r'\s+', '', regex=True).tolist()
    df.columns = headers

    # 컬럼 매칭 (유연하게 찾기)
    col_map = {}
    for c in df.columns:
        if '연' in c: col_map['y'] = c
        elif '월' in c: col_map['m'] = c
        elif '일' in c: col_map['d'] = c
        elif '계획' in c and 'GJ' in c: col_map['p_gj'] = c
        elif '실적' in c and 'GJ' in c: col_map['a_gj'] = c
        elif '계획' in c and 'm3' in c: col_map['p_m3'] = c
        elif '실적' in c and 'm3' in c: col_map['a_m3'] = c

    # 날짜 생성
    try:
        df['날짜'] = pd.to_datetime({
            'year': pd.to_numeric(df[col_map['y']], errors='coerce'),
            'month': pd.to_numeric(df[col_map['m']], errors='coerce'),
            'day': pd.to_numeric(df[col_map['d']], errors='coerce')
        }, errors='coerce')
        df = df.dropna(subset=['날짜'])
    except:
        return None, "❌ 날짜 변환 실패. 연/월/일 데이터가 숫자인지 확인하세요."

    # 숫자 데이터 정리 (편집하기 좋게 정리)
    # 편집용 최종 데이터프레임 생성
    edit_df = pd.DataFrame()
    edit_df['날짜'] = df['날짜']
    edit_df['연'] = df[col_map['y']]
    edit_df['월'] = df[col_map['m']]
    edit_df['일'] = df[col_map['d']]
    
    # 숫자 변환 (빈값은 0)
    edit_df['계획(GJ)'] = pd.to_numeric(df[col_map['p_gj']], errors='coerce').fillna(0)
    edit_df['계획(m3)'] = pd.to_numeric(df[col_map['p_m3']], errors='coerce').fillna(0)
    # 실적은 입력해야 하므로 NaN도 허용하지만 계산을 위해 일단 0 처리
    edit_df['실적(GJ)'] = pd.to_numeric(df[col_map['a_gj']], errors='coerce').fillna(0)
    edit_df['실적(m3)'] = pd.to_numeric(df[col_map['a_m3']], errors='coerce').fillna(0)

    return edit_df, None

# --- 세션 상태 관리 (데이터 편집 보존용) ---
if 'data' not in st.session_state:
    st.session_state.data = None

# 사이드바: 파일 업로드
st.sidebar.header("📂 데이터 파일 관리")
uploaded_file = st.sidebar.file_uploader("엑셀 파일 업로드 (초기화)", type=['xlsx'])
DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

# 파일 로드 로직
if uploaded_file:
    df, err = process_excel(uploaded_file)
    if err: st.error(err)
    else: st.session_state.data = df
elif st.session_state.data is None:
    # 처음에만 기본 파일 로드
    try:
        df, err = process_excel(DEFAULT_FILE)
        if df is not None: st.session_state.data = df
    except:
        st.warning("기본 데이터 파일을 찾을 수 없습니다. 파일을 업로드해주세요.")

# 데이터가 없으면 중단
if st.session_state.data is None:
    st.stop()

df = st.session_state.data

# --- 메인 화면 UI ---
st.title("🔥 도시가스 공급실적 관리 시스템")

# 1. 날짜 선택 (작게 만들기)
col_input, col_space = st.columns([1, 5])
with col_input:
    # 날짜 입력 라벨을 숨기고 컴팩트하게
    selected_date = st.date_input(
        "기준일", 
        value=df['날짜'].min(), 
        label_visibility="collapsed"
    )
target_date = pd.to_datetime(selected_date)

# 2. 지표 계산 (편집된 데이터 실시간 반영)
def calc_metrics(df, t):
    # 날짜 필터
    mask_day = df['날짜'] == t
    mask_mtd = (df['날짜'] <= t) & (df['날짜'].dt.month == t.month) & (df['날짜'].dt.year == t.year)
    mask_ytd = (df['날짜'] <= t) & (df['날짜'].dt.year == t.year)
    
    res = {}
    for label, mask in zip(['Daily', 'MTD', 'YTD'], [mask_day, mask_mtd, mask_ytd]):
        d = df[mask]
        p = d['계획(GJ)'].sum()
        a = d['실적(GJ)'].sum()
        m3 = d['실적(m3)'].sum() / 1000 # 천 m3
        
        # 진도율: 계획이 0이면 0% 처리
        rate = (a / p * 100) if p > 0 else 0
        res[label] = {'p': p, 'a': a, 'm3': m3, 'rate': rate}
    return res

metrics = calc_metrics(df, target_date)

# 3. 지표 출력 (1번째 사진 스타일)
st.markdown("---")
c1, c2, c3 = st.columns(3)

# 일간
with c1:
    st.metric(
        label=f"일간 실적 ({target_date.strftime('%m/%d')})",
        value=f"{metrics['Daily']['a']:,.0f} GJ",
        delta=f"{metrics['Daily']['rate']-100:.1f}% (계획대비)"
    )
    st.caption(f"🎯 당일 계획: {metrics['Daily']['p']:,.0f} GJ")

# 월간 누계 (선택일까지의 계획 vs 실적)
with c2:
    st.metric(
        label="월간 누적 달성률 (MTD)",
        value=f"{metrics['MTD']['rate']:.1f}%",
        delta=f"{metrics['MTD']['a'] - metrics['MTD']['p']:,.0f} GJ (차이)"
    )
    st.caption(f"🔥 누적 계획: {metrics['MTD']['p']:,.0f} GJ")
    st.text(f"💧 실적(부피): {metrics['MTD']['m3']:,.1f} 천 m³")

# 연간 누계
with c3:
    st.metric(
        label="연간 누적 달성률 (YTD)",
        value=f"{metrics['YTD']['rate']:.1f}%",
        delta=f"{metrics['YTD']['a'] - metrics['YTD']['p']:,.0f} GJ (차이)"
    )
    st.caption(f"🔥 연간 계획: {metrics['YTD']['p']:,.0f} GJ")

st.markdown("---")

# 4. [핵심 기능] 데이터 입력 테이블 (3번째 사진 스타일)
st.subheader(f"📝 실적 데이터 입력 ({target_date.month}월)")
st.info("아래 표에서 '실적(GJ)'과 '실적(m3)'을 직접 수정하면 위 대시보드에 즉시 반영됩니다.")

# 해당 월의 데이터만 필터링해서 보여줌 (편집 편의성)
mask_view = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month)
view_df = df.loc[mask_view, ['날짜', '연', '월', '일', '계획(GJ)', '계획(m3)', '실적(GJ)', '실적(m3)']]

# 데이터 에디터 (수정 가능!)
edited_view = st.data_editor(
    view_df,
    hide_index=True,
    column_config={
        "날짜": st.column_config.DateColumn("날짜", format="YYYY-MM-DD", disabled=True),
        "연": None, "월": None, "일": None, # 연월일 컬럼은 숨김 (날짜가 있으니까)
        "계획(GJ)": st.column_config.NumberColumn("계획(GJ)", format="%d", disabled=True), # 계획은 수정 불가
        "실적(GJ)": st.column_config.NumberColumn("실적(GJ) ✏️", format="%d"), # 수정 가능
        "실적(m3)": st.column_config.NumberColumn("실적(m3) ✏️", format="%d"), # 수정 가능
    },
    use_container_width=True,
    height=400
)

# 5. 수정된 데이터를 원본에 반영
if not edited_view.equals(view_df):
    # 수정된 내용을 전체 데이터프레임에 업데이트
    df.update(edited_view)
    st.session_state.data = df
    st.rerun() # 화면 새로고침해서 그래프 갱신

# (선택사항) 수정된 파일 다운로드 기능
if st.button("💾 수정한 엑셀 파일 다운로드"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='연간', index=False)
    st.download_button(
        label="다운로드 시작",
        data=output.getvalue(),
        file_name="수정된_실적데이터.xlsx",
        mime="application/vnd.ms-excel"
    )
