import streamlit as st
import pandas as pd
import os

# 1. 페이지 설정
st.set_page_config(layout="wide", page_title="마케팅팀 Smart Marketing Hub")

# --------------------------------------------------------------------------
# [진단] 엑셀 파일을 유연하게 읽어오는 함수
# --------------------------------------------------------------------------
def load_data_debug():
    file_name = 'marketing_hub.xlsx' 
    
    if not os.path.exists(file_name):
        st.error(f"❌ '{file_name}' 파일이 없습니다. 파일명을 확인해주세요.")
        return pd.DataFrame()

    try:
        # 일단 헤더 없이 싹 다 읽어봅니다.
        df_raw = pd.read_excel(file_name, engine='openpyxl', header=None)
        
        # '구분'이라는 글자가 들어있는 행(Row)을 찾습니다. (거기가 진짜 제목 줄이니까요)
        header_row_idx = -1
        for idx, row in df_raw.iterrows():
            # 행을 문자열로 바꿔서 '구분'과 '내용'이 있는지 검사
            row_str = " ".join(row.astype(str))
            if "구분" in row_str and "내용" in row_str:
                header_row_idx = idx
                break
        
        if header_row_idx == -1:
            st.error("❌ 엑셀에서 '구분'과 '내용'이라고 적힌 제목 줄을 찾을 수 없습니다.")
            return pd.DataFrame()

        # 찾은 위치부터 다시 제대로 읽습니다.
        df = pd.read_excel(file_name, engine='openpyxl', header=header_row_idx)
        
        # [핵심 해결] '구분' 열이 병합된 셀이면 비어있으므로, 위쪽 값을 복사해 채웁니다.
        if '구분' in df.columns:
            df['구분'] = df['구분'].ffill()
            
        return df

    except Exception as e:
        st.error(f"❌ 에러 발생: {e}")
        return pd.DataFrame()

# --------------------------------------------------------------------------
# [디자인] 스타일 설정
# --------------------------------------------------------------------------
st.markdown("""
<style>
    body { font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif; color: #333; }
    .main-title { font-size: 28px; font-weight: 800; margin-bottom: 30px; color: #2c3e50; }
    .section-header { font-size: 18px; font-weight: 700; color: #1e40af; margin-top: 40px; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
    .divider-top { border-top: 2px solid #1e40af; margin-bottom: 0; }
    .list-row { display: flex; justify-content: space-between; align-items: center; padding: 15px 10px; border-bottom: 1px solid #e5e7eb; }
    .content-area { flex: 3; font-size: 15px; }
    .content-title { font-weight: 700; margin-right: 5px; }
    .content-desc { color: #555; font-size: 14px; }
    .star-rating { flex: 0.5; text-align: center; font-size: 14px; letter-spacing: 2px; color: #333; }
    .link-area { flex: 0.5; text-align: right; }
    .link-btn { display: inline-block; padding: 6px 20px; border: 1px solid #d1d5db; border-radius: 6px; background-color: white; text-decoration: none; color: #555; font-size: 13px; transition: background-color 0.2s; }
    .link-btn:hover { background-color: #f3f4f6; }
    .folder-icon { color: #fbbf24; }
</style>
""", unsafe_allow_html=True)

# --------------------------------------------------------------------------
# [실행] 화면 그리기
# --------------------------------------------------------------------------

# 1. 타이틀
st.markdown('<div class="main-title">🔥 마케팅팀 _ Smart Marketing Hub</div>', unsafe_allow_html=True)

# 2. 데이터 로드 시도
df = load_data_debug()

# 3. [진단용] 데이터가 잘 읽혔는지 화면 맨 위에 표로 보여줍니다. (성공 후 지우면 됨)
if not df.empty:
    with st.expander("🔍 엑셀 데이터가 제대로 읽혔는지 확인하기 (클릭)"):
        st.dataframe(df) # 여기서 데이터가 보이면 성공입니다!

    # 4. 실제 디자인 적용
    # '구분' 컬럼이 있는지 확인
    if '구분' in df.columns:
        categories = df['구분'].unique()
        
        for category in categories:
            # 카테고리 이름이 비어있으면(nan) 건너뜀
            if pd.isna(category): continue

            st.markdown(f"""
                <div class="section-header">
                    <span class="folder-icon">📂</span> {category}
                </div>
                <div class="divider-top"></div>
            """, unsafe_allow_html=True)

            section_data = df[df['구분'] == category]

            for index, row in section_data.iterrows():
                # 컬럼 이름이 조금 달라도 처리되도록 방어 코드 작성
                title = row['내용'] if '내용' in df.columns else "제목없음"
                
                # '기능' 혹은 '설명' 컬럼 찾기
                desc = ""
                if '기능' in df.columns: desc = row['기능']
                elif '설명' in df.columns: desc = row['설명']
                if pd.isna(desc): desc = ""

                # 별점 ('활용도' 혹은 '별점')
                stars = ""
                if '활용도' in df.columns: stars = row['활용도']
                if pd.isna(stars): stars = ""

                # 링크 ('링크' 혹은 'Link')
                link = "#"
                if '링크' in df.columns and not pd.isna(row['링크']): link = row['링크']
                elif 'Link' in df.columns and not pd.isna(row['Link']): link = row['Link']

                st.markdown(f"""
                <div class="list-row">
                    <div class="content-area">
                        <span class="content-title">{title}</span>
                        <span class="content-desc">{desc}</span>
                    </div>
                    <div class="star-rating">{stars}</div>
                    <div class="link-area"><a href="{link}" target="_blank" class="link-btn">Link 🔗</a></div>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("<div style='margin-bottom: 40px;'></div>", unsafe_allow_html=True)
    else:
        st.error("엑셀 파일은 읽었지만 '구분'이라는 제목의 열을 찾지 못했습니다. 엑셀 제목을 확인해주세요.")

else:
    st.warning("데이터를 불러오지 못했습니다. 위의 에러 메시지를 확인해주세요.")
