# Build Week verified Replay script

This script is fictional and contains no personal or company meeting data. It is designed for one 60–90 second Korean → English run through the real application pipeline.

## Recording settings

- STT: Deepgram Nova-3, Korean
- Translation: Gemini 3.1 Flash Lite, Korean → English
- Decision Radar: OpenAI GPT-5.6 Luna, English output
- Context profile: `Build Week Demo EN`
- Approved terms and people:
  - `Aster Bridge` — aliases `아스터 브릿지`, `아스타 브리지`, `아스터브리지`, `아스터 브리지`
  - `Fit & Gap` — aliases `핏앤갭`, `핏 앤 갭`
  - `Mina Kim` — aliases `김민아`, `민아 김`
  - `Junho Park` — aliases `박준호`, `준호 박`
  - `Design B` — aliases `B안`, `비안`
  - `screen specification` — aliases `화면 명세서`, `하면 명세서`
  - `three companies` — aliases `세 개 회사`, `세 회사`, `새 회사`
- Pause about 0.5 seconds between sentences. Do not add speech outside the script.

## Korean meeting script

오늘 회의에서는 아스터 브릿지 베타 공개 일정, 시험 도입 회사 수, 화면 디자인, 비용과 법무 과제를 확인하겠습니다.

부하 시험과 법무 확인 시간을 확보하기 위해 베타 공개일은 8월 20일로 확정합니다.

시험 도입은 지원 여력을 고려해 세 개 회사부터 시작하기로 결정했습니다.

김민아 님은 후보 회사의 참여 여부를 7월 22일 오후 5시까지 확인해 주세요.

네, 제가 그때까지 세 회사에 확인하고 결과를 공유하겠습니다.

화면 디자인은 사용자 테스트 점수가 높았던 B안을 정식으로 채택합니다.

박준호 님은 오늘 안에 일정표와 화면 명세서를 업데이트해 주세요.

추가 번역 서버가 포함된 수정 견적서는 7월 21일 오후 3시까지 제출하겠습니다.

다만 정확한 월 서버 비용은 공급업체에 확인 중이라 아직 결정하지 못했습니다.

해외 이용 약관은 법무팀이 7월 23일 정오까지 확인합니다.

영어 지원은 자막만 제공하는 경우와 화면 전체를 영어로 바꾸는 경우의 작업량을 비교해 보겠습니다.

제품의 공식 영문 이름과 주말 지원 담당자는 오늘 결정하지 않고 다음 회의에서 계속 논의하겠습니다.

다음 진척 회의는 7월 24일 오전 10시입니다.

## Intended evaluation signals

These are test intentions, not prewritten model output. The public fixture must contain the real Provider results without rewriting them.

- Context correction for at least one approved name or term.
- Explicit decisions: August 20 launch, three-company pilot, design B.
- Actions with evidence: candidate confirmation, document update, revised quote, legal review.
- Unresolved issues: exact monthly server cost, official English product name, weekend support owner.
- Every Radar evidence ID resolves to a finalized Korean source segment.
- English translation and English Radar text remain understandable without Korean knowledge.
