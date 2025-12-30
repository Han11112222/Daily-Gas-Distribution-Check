import streamlit as st
import pandas as pd
import time

# 1. 페이지 기본 설정 (가로로 넓게 보기)
st.set_page_config(page_title="도시가스 공급실적 관리", layout="wide")

# --- 내부 함수: 엑셀 데이터 로드 및 전처리 ---
def load_excel_file(file_source):
    # (1) 헤더 없이 읽어서 데이터 구조 파악
    try:
        raw = pd.read_excel(file_source, sheet_name='연간', header=None)
    except:
        # 시트 이름이 다를 경우 첫 번째 시트 로드
        raw = pd.read_excel(file_source, sheet_name=0, header=None)

    # (2) '연', '월', '일'이 모두 들어있는 행(Header) 찾기
    header_row_index = None
    for i, row in raw.iterrows():
        row_values = row.astype(str).values
        if '연' in row_values and '월' in row_values and '일' in row_values:
            header_row_index = i
            break
    
    if header_row_index is None:
        return None, "❌ 엑셀 파일에서 [연, 월, 일] 컬럼을 찾을 수 없습니다."

    # (3) 데이터 본문 추출 및 컬럼명 지정
    df = raw.iloc[header_row_index+1:].copy()
    # 컬럼명에서 공백 제거 (예: '계획 (GJ)' -> '계획(GJ)')
    df.columns = raw.iloc[header_row_index].astype(str).str.replace(r'\s+', '', regex=True).tolist()

    # (4) 핵심 컬럼 매핑 (이름이 조금 달라도 단어로 찾기)
    col_map = {}
    for c in df.columns:
        if '연' in c and len(c) < 5: col_map['y'] = c
        elif '월' in c and len(c) < 5: col_map['m'] = c
        elif '일' in c and len(c) < 5: col_map['d'] = c
        elif '계획' in c and 'GJ' in c: col_map['p_gj'] = c
        elif '실적' in c and 'GJ' in c: col_map['a_gj'] = c
        elif '실적' in c and 'm3' in c: col_map['a_m3'] = c

    # (5) 날짜 컬럼 생성 (연+월+일)
    try:
        df['날짜'] = pd.to_datetime({
            'year': pd.to_numeric(df[col_map['y']], errors='coerce'),
            'month': pd.to_numeric(df[col_map['m']], errors='coerce'),
            'day': pd.to_numeric(df[col_map['d']], errors='coerce')
        }, errors='coerce')
        # 날짜 변환 실패한 행(빈 행 등) 제거
        df = df.dropna(subset=['날짜'])
    except:
        return None, "❌ 날짜 변환 중 오류가 발생했습니다. 연/월/일 데이터 형식을 확인하세요."

    # (6) 계산용 표준 컬럼 생성 (숫자 강제 변환, 빈값은 0)
    # 원본 데이터를 유지하면서 계산용 컬럼을 따로 만듭니다.
    df['calc_p_gj'] = pd.to_numeric(df[col_map['p_gj']], errors='coerce').fillna(0)
    df['calc_a_gj'] = pd.to_numeric(df[col_map['a_gj']], errors='coerce').fillna(0)
    df['calc_a_m3'] = pd.to_numeric(df[col_map['a_m3']], errors='coerce').fillna(0)
    
    # UI 편집용 컬럼 이름 매핑 (사용자에게 보여줄 이름)
    # 실제 데이터프레임의 컬럼명을 우리가 원하는 표준 이름으로 바꿈
    rename_dict = {
        col_map['p_gj']: '계획(GJ)',
        col_map['a_gj']: '실적(GJ)',
        col_map['a_m3']: '실적(m3)'
    }
    df = df.rename(columns=rename_dict)
    
    # 필요한 컬럼만 남기고 정렬
    final_cols = ['날짜', '연', '월', '일', '계획(GJ)', '실적(GJ)', '실적(m3)']
    # 만약 원본에 없는 컬럼이 있다면 에러 방지를 위해 처리
    available_cols = [c for c in final_cols if c in df.columns]
    df = df[available_cols]
    
    return df, None

# --- 시스템 상태 관리 (데이터 유지용) ---
if 'data_df' not in st.session_state:
    st.session_state.data_df = None

# --- 사이드바: 파일 로드 ---
st.sidebar.header("📂 데이터 파일")
uploaded_file = st.sidebar.file_uploader("엑셀 파일 업로드 (초기화)", type=['xlsx'])
DEFAULT_FILE = "2026_연간_일별공급계획_2.xlsx"

# 파일이 업로드되면 데이터를 새로 읽음
if uploaded_file:
    loaded_df, err_msg = load_excel_file(uploaded_file)
    if err_msg:
        st.error(err_msg)
    else:
        st.session_state.data_df = loaded_df
        st.sidebar.success("✅ 파일 로드 성공")

# 업로드된 파일이 없으면 기본 파일 로드 시도 (최초 1회)
elif st.session_state.data_df is None:
    try:
        loaded_df, err_msg = load_excel_file(DEFAULT_FILE)
        if loaded_df is not None:
            st.session_state.data_df = loaded_df
            st.sidebar.info("ℹ️ 기본 데이터 사용 중")
        else:
            st.warning("기본 파일을 찾을 수 없습니다. 파일을 업로드해주세요.")
    except Exception as e:
        st.error(f"기본 파일 로드 중 에러: {e}")

# 데이터가 없으면 여기서 멈춤
if st.session_state.data_df is None:
    st.stop()

# 작업용 데이터프레임 가져오기
df = st.session_state.data_df

# --- 메인 화면 UI ---
st.title("🔥 도시가스 공급실적 관리")

# 1. 날짜 선택 (요청하신 대로 컴팩트하게)
col_date, col_dummy = st.columns([1, 4])
with col_date:
    selected_date = st.date_input(
        "조회 기준일",
        value=df['날짜'].min(),
        label_visibility="collapsed" # 라벨 숨김
    )
target_date = pd.to_datetime(selected_date)

# 2. 진도율 계산 로직 (형님의 100% 매칭 로직 적용)
# 데이터프레임의 값은 '계획(GJ)', '실적(GJ)' 등의 컬럼에 있습니다.
def calculate_kpis(data, t_date):
    # 날짜 필터링
    mask_day = data['날짜'] == t_date
    mask_mtd = (data['날짜'] <= t_date) & (data['날짜'].dt.month == t_date.month) & (data['날짜'].dt.year == t_date.year)
    mask_ytd = (data['날짜'] <= t_date) & (data['날짜'].dt.year == t_date.year)
    
    kpis = {}
    for label, mask in zip(['day', 'mtd', 'ytd'], [mask_day, mask_mtd, mask_ytd]):
        subset = data[mask]
        
        # 숫자형으로 확실하게 변환 후 합계 (에러 방지)
        p = pd.to_numeric(subset['계획(GJ)'], errors='coerce').fillna(0).sum()
        a = pd.to_numeric(subset['실적(GJ)'], errors='coerce').fillna(0).sum()
        m3 = pd.to_numeric(subset['실적(m3)'], errors='coerce').fillna(0).sum() / 1000 # 천 m3
        
        # 달성률 (분모가 0이면 0%)
        rate = (a / p * 100) if p > 0 else 0
        kpis[label] = {'p': p, 'a': a, 'm3': m3, 'rate': rate}
        
    return kpis

# 현재 데이터로 지표 계산
metrics = calculate_kpis(df, target_date)

# 3. 대시보드 출력
st.markdown("---")
c1, c2, c3 = st.columns(3)

# (1) 일간 실적
with c1:
    st.metric(
        label=f"일간 실적 ({target_date.strftime('%m.%d')})",
        value=f"{metrics['day']['a']:,.0f} GJ",
        delta=f"{metrics['day']['rate']-100:.1f}% (계획대비)"
    )
    st.caption(f"🎯 당일 계획: {metrics['day']['p']:,.0f} GJ")

# (2) 월간 누계 (선택일까지)
with c2:
    st.metric(
        label="월간 누계 진도율 (MTD)",
        value=f"{metrics['mtd']['rate']:.1f}%",
        delta=f"{metrics['mtd']['a'] - metrics['mtd']['p']:,.0f} GJ (차이)"
    )
    st.caption(f"🔥 누적 계획: {metrics['mtd']['p']:,.0f} GJ")
    st.text(f"💧 실적(부피): {metrics['mtd']['m3']:,.1f} 천 m³")

# (3) 연간 누계 (선택일까지)
with c3:
    st.metric(
        label="연간 누계 진도율 (YTD)",
        value=f"{metrics['ytd']['rate']:.1f}%",
        delta=f"{metrics['ytd']['a'] - metrics['ytd']['p']:,.0f} GJ (차이)"
    )
    st.caption(f"🔥 누적 계획: {metrics['ytd']['p']:,.0f} GJ")

st.markdown("---")

# 4. [핵심] 데이터 입력 및 수정 (3번째 사진 스타일)
st.subheader(f"📝 {target_date.month}월 실적 입력")
st.info("아래 표의 '실적' 칸을 클릭하여 수정한 후 엔터(Enter)를 치면 위 그래프가 즉시 반영됩니다.")

# 편집 편의를 위해 해당 월의 데이터만 필터링해서 보여줌
mask_view = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month)
display_cols = ['날짜', '계획(GJ)', '실적(GJ)', '실적(m3)']
view_df = df.loc[mask_view, display_cols].copy()

# 데이터 에디터 설정
edited_df = st.data_editor(
    view_df,
    column_config={
        "날짜": st.column_config.DateColumn("공급일자", format="YYYY-MM-DD", disabled=True),
        "계획(GJ)": st.column_config.NumberColumn("계획(GJ)", format="%d", disabled=True), # 계획 수정 불가
        "실적(GJ)": st.column_config.NumberColumn("실적(GJ) ✏️", format="%d", min_value=0),
        "실적(m3)": st.column_config.NumberColumn("실적(m3) ✏️", format="%d", min_value=0),
    },
    hide_index=True,
    use_container_width=True,
    num_rows="fixed" # 행 추가/삭제 불가능하게 (날짜 고정)
)

# 5. 수정 사항 실시간 반영 로직
# 에디터의 내용이 변경되었는지 확인
if not edited_df.equals(view_df):
    # 전체 데이터프레임(df)에서 해당 월 부분만 업데이트
    df.update(edited_df)
    # 세션 상태에 저장하여 새로고침 후에도 유지
    st.session_state.data_df = df
    # 그래프 갱신을 위해 페이지 리로드
    st.rerun()

# (선택) 수정된 파일 다운로드
st.markdown("---")
import io
buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
    df.to_excel(writer, sheet_name='연간', index=False)
    
st.download_button(
    label="💾 현재 수정된 데이터 엑셀로 저장",
    data=buffer,
    file_name=f"실적데이터_{target_date.strftime('%Y%m%d')}.xlsx",
    mime="application/vnd.ms-excel"
)
