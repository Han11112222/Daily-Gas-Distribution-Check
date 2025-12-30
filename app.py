import streamlit as st
import pandas as pd
import io

# 1. 화면 설정 (넓게 보기)
st.set_page_config(page_title="도시가스 공급실적 관리", layout="wide")

# --- 내부 함수: 엑셀 읽기 및 전처리 ---
def load_excel(file):
    try:
        raw = pd.read_excel(file, sheet_name='연간', header=None)
    except:
        raw = pd.read_excel(file, sheet_name=0, header=None)

    # 헤더(연, 월, 일) 찾기
    header_idx = None
    for i, row in raw.iterrows():
        vals = row.astype(str).values
        if '연' in vals and '월' in vals and '일' in vals:
            header_idx = i
            break
            
    if header_idx is None:
        return None, "❌ [연, 월, 일] 컬럼을 찾을 수 없습니다."

    # 데이터 추출 및 컬럼명 정리
    df = raw.iloc[header_idx+1:].copy()
    df.columns = raw.iloc[header_idx].astype(str).str.replace(r'\s+', '', regex=True).tolist()

    # 컬럼 매칭 (예상/계획, GJ/m3 유연하게 찾기)
    col_map = {}
    for c in df.columns:
        if '연' in c: col_map['y'] = c
        elif '월' in c: col_map['m'] = c
        elif '일' in c: col_map['d'] = c
        elif ('계획' in c or '예상' in c) and 'GJ' in c: col_map['p_gj'] = c
        elif '실적' in c and 'GJ' in c: col_map['a_gj'] = c
        elif ('계획' in c or '예상' in c) and 'm3' in c: col_map['p_m3'] = c
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

        # 표준 컬럼 생성 (모두 숫자로 변환)
        df['계획(GJ)'] = pd.to_numeric(df[col_map.get('p_gj')], errors='coerce').fillna(0)
        df['실적(GJ)'] = pd.to_numeric(df[col_map.get('a_gj')], errors='coerce').fillna(0)
        # m3는 원본 그대로 가져옴 (나중에 화면에서만 나누기 위해)
        df['계획(m3)'] = pd.to_numeric(df[col_map.get('p_m3')], errors='coerce').fillna(0)
        df['실적(m3)'] = pd.to_numeric(df[col_map.get('a_m3')], errors='coerce').fillna(0)
        
        # 필요한 컬럼만 선택
        df = df[['날짜', '계획(GJ)', '실적(GJ)', '계획(m3)', '실적(m3)']]
        
    except Exception as e:
        return None, f"❌ 데이터 변환 오류: {e}"

    return df, None

# --- 세션 상태 (데이터 유지) ---
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
            st.sidebar.info("ℹ️ 기본 파일 로드됨")
    except:
        st.warning("기본 파일을 찾을 수 없습니다.")

if st.session_state.data is None:
    st.stop()

# 메인 데이터프레임
df = st.session_state.data

# --- 메인 화면 ---
st.title("🔥 도시가스 공급실적 관리")

# 1. 날짜 선택 (작게)
col_date, col_space = st.columns([1, 5])
with col_date:
    selected_date = st.date_input(
        "조회 기준일", 
        value=df['날짜'].min(), 
        label_visibility="collapsed"
    )
target_date = pd.to_datetime(selected_date)

# 2. 진도율 계산
def calc_kpi(data, t):
    mask_day = data['날짜'] == t
    mask_mtd = (data['날짜'] <= t) & (data['날짜'].dt.month == t.month) & (data['날짜'].dt.year == t.year)
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

# 3. 지표 출력 (천단위 쉼표 적용)
st.markdown("---")
c1, c2, c3 = st.columns(3)

with c1:
    st.metric(
        label=f"일간 실적 ({target_date.strftime('%m.%d')})",
        value=f"{int(metrics['Day']['a']):,} GJ",
        delta=f"{metrics['Day']['rate']-100:.1f}%"
    )
    st.caption(f"🎯 당일 계획: {int(metrics['Day']['p']):,} GJ")

with c2:
    st.metric(
        label="월간 누적 진도율 (MTD)",
        value=f"{metrics['MTD']['rate']:.1f}%",
        delta=f"{int(metrics['MTD']['a'] - metrics['MTD']['p']):,} GJ"
    )
    st.caption(f"🔥 누적 계획: {int(metrics['MTD']['p']):,} GJ")
    st.text(f"💧 실적(부피): {int(metrics['MTD']['m3']):,} 천 m³")

with c3:
    st.metric(
        label="연간 누적 진도율 (YTD)",
        value=f"{metrics['YTD']['rate']:.1f}%",
        delta=f"{int(metrics['YTD']['a'] - metrics['YTD']['p']):,} GJ"
    )
    st.caption(f"🔥 누적 계획: {int(metrics['YTD']['p']):,} GJ")

st.markdown("---")

# --- 4. 데이터 입력 테이블 (분리형) ---
st.subheader(f"📝 {target_date.month}월 실적 입력")
st.info("실적을 입력하고 엔터(Enter)를 치면 상단 그래프에 반영됩니다. (모든 숫자는 정수 표기)")

# (1) 열량(GJ) 테이블
st.markdown("##### 1️⃣ 열량(GJ) 입력")
mask_month = (df['날짜'].dt.year == target_date.year) & (df['날짜'].dt.month == target_date.month)

# GJ용 뷰 생성
view_gj = df.loc[mask_month, ['날짜', '계획(GJ)', '실적(GJ)']].copy()

edited_gj = st.data_editor(
    view_gj,
    column_config={
        "날짜": st.column_config.DateColumn("공급일자", format="YYYY-MM-DD", disabled=True),
        "계획(GJ)": st.column_config.NumberColumn("계획(GJ)", format="%d", disabled=True),
        "실적(GJ)": st.column_config.NumberColumn("실적(GJ) ✏️", format="%d", min_value=0),
    },
    hide_index=True,
    use_container_width=True,
    key="editor_gj" # 키 설정 중요
)

# GJ 수정 반영
if not edited_gj.equals(view_gj):
    df.update(edited_gj)
    st.session_state.data = df
    st.rerun()

st.markdown("---")

# (2) 부피(천 m3) 테이블
st.markdown("##### 2️⃣ 부피(천 m³) 입력")

# m3용 뷰 생성 (원본 m3 데이터를 1000으로 나눠서 표시)
view_m3_raw = df.loc[mask_month, ['날짜', '계획(m3)', '실적(m3)']].copy()
view_m3_display = view_m3_raw.copy()
view_m3_display['계획(천m3)'] = (view_m3_raw['계획(m3)'] / 1000).round(0).astype(int)
view_m3_display['실적(천m3)'] = (view_m3_raw['실적(m3)'] / 1000).round(0).astype(int)
# 표시용 데이터프레임 정리
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

# m3 수정 반영 logic (입력된 천단위 값을 다시 1000 곱해서 원본에 저장)
# 사용자가 실적(천m3)을 변경했는지 확인
if not edited_m3.equals(view_m3_display):
    # 변경된 행을 찾아 원본(m3)에 반영
    # 날짜를 인덱스로 사용하여 매핑하는 것이 안전함
    
    # 수정된 천m3 값을 가져와서 1000을 곱함
    new_raw_m3 = edited_m3['실적(천m3)'] * 1000
    
    # 원본 데이터프레임(df)의 해당 위치 업데이트
    # 인덱스가 일치한다고 가정 (mask_month로 잘랐으므로)
    df.loc[mask_month, '실적(m3)'] = new_raw_m3.values
    
    st.session_state.data = df
    st.rerun()

# (선택) 엑셀 다운로드
st.markdown("---")
buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
    df.to_excel(writer, sheet_name='연간', index=False)
    
st.download_button(
    label="💾 엑셀 파일 다운로드",
    data=buffer,
    file_name=f"실적데이터_{target_date.strftime('%Y%m%d')}.xlsx",
    mime="application/vnd.ms-excel"
)
