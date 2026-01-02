import streamlit as st
import pandas as pd
import datetime

# --- [설정] 페이지 기본 설정 ---
st.set_page_config(layout="wide", page_title="도시가스 공급실적 관리")

# --- [스타일] CSS 적용 (매트릭스 높이 2배 확대 포함) ---
st.markdown("""
    <style>
    /* 1. 전체 폰트 및 가독성 조정 */
    .block-container { padding-top: 2rem; }
    
    /* 2. 매트릭스(지표) 박스 세로 크기 2배 확대 */
    div[data-testid="stMetric"] {
        background-color: #F0F2F6;
        border-radius: 10px;
        padding: 20px 10px;
        min-height: 200px; /* 높이를 강제로 늘림 (기본의 약 2배) */
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    
    /* 3. 탭 폰트 크기 키우기 */
    button[data-baseweb="tab"] {
        font-size: 18px;
        font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

# --- [함수] 데이터 로드 (캐싱) ---
@st.cache_data
def load_data():
    # 예시 데이터 생성 (실제 사용시에는 엑셀 업로드 로직 사용)
    # Han형님, 여기서는 테스트를 위해 2026년 1월 1일 데이터를 포함한 더미를 만듭니다.
    # 실제 파일 업로드 기능과 연결하시면 됩니다.
    dates = pd.date_range(start='2020-01-01', end='2026-01-01', freq='D')
    data = {
        'date': dates,
        'year': dates.year,
        'month': dates.month,
        'day': dates.day,
        'supply_gj': [200000 + (i % 100) * 1000 for i in range(len(dates))], # 임의 데이터
        'plan_gj': [210000 for _ in range(len(dates))],
        'supply_m3': [5000 for _ in range(len(dates))],
        'plan_m3': [5200 for _ in range(len(dates))]
    }
    df = pd.DataFrame(data)
    # 2026-01-01 값을 초기엔 0이나 비워둘 수 있음, 여기선 테스트용 값
    return df

# --- [함수] 랭킹 계산 (Tab 1, Tab 2 공통 사용) ---
def calculate_ranking(df, target_date, target_value):
    """
    특정 날짜의 공급량이 전체 기간 중 몇 위인지, 동월 중 몇 위인지 계산
    """
    if target_value == 0 or pd.isna(target_value):
        return "-", "-"
    
    # 1. 역대 전체 랭킹
    total_rank = (df['supply_gj'] > target_value).sum() + 1
    
    # 2. 역대 동월(1월이면 역대 모든 1월) 중 랭킹
    target_month = target_date.month
    month_df = df[df['date'].dt.month == target_month]
    month_rank = (month_df['supply_gj'] > target_value).sum() + 1
    
    return total_rank, month_rank

# --- 메인 로직 시작 ---
st.title("🔥 도시가스 공급실적 관리 시스템")

# 1. 데이터 불러오기
if 'df' not in st.session_state:
    st.session_state['df'] = load_data()

# 탭 생성
tab1, tab2 = st.tabs(["📋 실적 관리 (입력)", "📊 공급량 분석 (랭킹)"])

# ==============================================================================
# [Tab 1] 실적 관리 (입력 및 KPI)
# ==============================================================================
with tab1:
    st.subheader("📅 일일 실적 입력 및 현황")

    # 1-1. 날짜 선택
    col_date, _ = st.columns([1, 3])
    with col_date:
        selected_date = st.date_input("조회/입력 날짜", datetime.date(2026, 1, 1))
        selected_date = pd.to_datetime(selected_date)

    # 1-2. 데이터 에디터 (여기서 먼저 수정을 받아야 상단 지표에 반영됨)
    st.info("👇 아래 표에서 실적을 수정하면, 상단 지표와 랭킹이 즉시 업데이트됩니다.")
    
    # 날짜 필터링 (표시용) - 전체 데이터를 다 보여주되, 선택된 날짜가 강조되거나 맨 위로 오게 할 수도 있음
    # 여기서는 사용자가 전체 데이터를 보면서 수정한다고 가정
    
    edited_df = st.data_editor(
        st.session_state['df'],
        use_container_width=True,
        num_rows="dynamic",
        key="editor",
        hide_index=True,
        column_config={
            "date": st.column_config.DateColumn("일자", format="YYYY-MM-DD"),
            "supply_gj": st.column_config.NumberColumn("실적(GJ)", format="%d"),
            "plan_gj": st.column_config.NumberColumn("계획(GJ)", format="%d"),
        }
    )

    # *** 중요: 에디터에서 수정된 내용을 바탕으로 지표 계산 ***
    # 선택된 날짜의 데이터 추출 (edited_df 사용)
    mask = edited_df['date'] == selected_date
    daily_data = edited_df[mask]

    if not daily_data.empty:
        current_gj = daily_data['supply_gj'].iloc[0]
        plan_gj = daily_data['plan_gj'].iloc[0]
        gap_gj = current_gj - plan_gj
        
        current_m3 = daily_data['supply_m3'].iloc[0]
        
        # 랭킹 계산 (수정된 df 기준)
        total_rank, month_rank = calculate_ranking(edited_df, selected_date, current_gj)
        
        rank_text = f"🏆 역대 {total_rank}위 | 📅 역대 {selected_date.month}월 중 {month_rank}위"
    else:
        current_gj, plan_gj, gap_gj, current_m3 = 0, 0, 0, 0
        rank_text = "데이터 없음"

    # 1-3. 상단 KPI 매트릭스 (에디터 아래에 배치하거나, st.container로 순서 조정 가능하나, 로직상 여기 둠)
    # Han형님 요청: Tab 2와 같은 랭킹 정보를 표시
    
    st.markdown("### 🔥 당일 공급 실적 요약")
    m1, m2, m3 = st.columns(3)
    
    with m1:
        st.metric(label="열량 실적 (GJ)", value=f"{current_gj:,.0f} GJ", delta=f"{gap_gj:,.0f} (계획대비)")
        # 랭킹 정보를 metric 아래에 표시
        if current_gj > 0:
            st.markdown(f":red[**{rank_text}**]")
            
    with m2:
        st.metric(label="부피 실적 (천㎥)", value=f"{current_m3:,.0f} 천㎥")
        
    with m3:
        # 달성률 등 추가 지표
        rate = (current_gj / plan_gj * 100) if plan_gj > 0 else 0
        st.metric(label="계획 달성률", value=f"{rate:.1f}%")


# ==============================================================================
# [Tab 2] 공급량 분석 (랭킹 상세) - Han형님 요청한 스타일 유지
# ==============================================================================
with tab2:
    st.subheader("💎 일별 공급량 Top 랭킹 분석")
    
    # 분석 기준 날짜 (Tab 1과 연동하거나 별도 선택)
    analysis_date = selected_date # Tab 1에서 선택한 날짜 연동
    
    # 분석 데이터 준비 (edited_df 사용해야 Tab 1 수정사항 반영됨)
    mask_ana = edited_df['date'] == analysis_date
    
    if not mask_ana.empty and mask_ana.any():
        val = edited_df[mask_ana]['supply_gj'].iloc[0]
        
        # 랭킹 재계산 (확인용)
        t_rank, m_rank = calculate_ranking(edited_df, analysis_date, val)
        
        # Han형님이 캡처해주신 파란색 박스 스타일 구현
        st.markdown(f"""
        <div style="background-color:#e8f4f9; padding:20px; border-radius:10px; border-left: 5px solid #ff4b4b;">
            <h3 style="margin:0; color:#333;">📊 {analysis_date.strftime('%Y년 %m월')} 최고 실적 분석 ({analysis_date.strftime('%Y년 %m월 %d일')})</h3>
            <p style="font-size:18px; margin-top:10px;">
                공급량: <strong>{val:,.1f} GJ</strong> 
                <span style="background-color:#fff; padding:5px 10px; border-radius:15px; border:1px solid #ddd; margin-left:10px;">
                    🏆 역대 전체 <strong>{t_rank}위</strong>
                </span>
                <span style="background-color:#fff; padding:5px 10px; border-radius:15px; border:1px solid #ddd; margin-left:5px;">
                    📅 역대 {analysis_date.month}월 중 <strong>{m_rank}위</strong>
                </span>
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # 랭킹 Top 3 카드 보여주기 (예시)
        top3 = edited_df.sort_values(by='supply_gj', ascending=False).head(3)
        c1, c2, c3 = st.columns(3)
        
        for idx, (i, row) in enumerate(top3.iterrows()):
            with [c1, c2, c3][idx]:
                st.info(f"🥇 역대 {idx+1}위\n\n📅 {row['date'].strftime('%Y-%m-%d')}\n\n🔥 {row['supply_gj']:,.1f} GJ")
                
    else:
        st.warning("선택한 날짜의 데이터가 없습니다.")
