# Smart Citizen — 법적 고지 및 규정 준수

이 페이지는 Smart Citizen의 모든 법적, 라이선스, 데이터 처리 관련 공개 사항을 한곳에 모아 놓았습니다. 여기 내용이 실행 파일 옆에 제공되는 `LICENSE` 또는 `NOTICE` 파일과 충돌하는 경우, 해당 파일이 우선합니다.

## Star Citizen / Cloud Imperium 감사의 말

Smart Citizen은 Star Citizen을 위한 **비공식 커뮤니티 도구**입니다. Cloud Imperium Games(CIG)나 Roberts Space Industries(RSI)에 의해 개발, 승인, 후원되거나 이들과 제휴하지 않았습니다. Smart Citizen은 팬이 만든 콘텐츠와 도구에 대한 CIG의 "Made by the Community" 지침 범위 안에 있습니다.

**Star Citizen®**, **Roberts Space Industries®**, **Cloud Imperium®**는 Cloud Imperium Rights LLC와 Cloud Imperium Rights Ltd.의 등록 상표입니다. `Data.p4k`의 내용, 함선 및 부품 모델, 아이템 이름, 임무 텍스트, 설정 자료를 포함한 모든 Star Citizen 게임 데이터는 Cloud Imperium Rights LLC의 지적 재산입니다.

Smart Citizen은 어떠한 CIG 또는 RSI 콘텐츠도 재배포하지 않습니다. 이 앱은 로컬 컴퓨터에 있는 **본인의 라이선스가 있는 Star Citizen 설치본**에서 파일을 읽고, 사용자가 사용자 지정한 텍스트를 동일한 설치본에 다시 씁니다. CIG 소유 콘텐츠는 Smart Citizen을 통해 컴퓨터 밖으로 나가지 않습니다.

## Smart Citizen 라이선스

Smart Citizen은 **Apache License, Version 2.0**에 따라 라이선스가 부여된 오픈 소스 소프트웨어입니다. 라이선스 사본은 [apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0)에서 확인할 수 있습니다. 전체 라이선스 텍스트는 실행 파일 옆의 `LICENSE` 파일에 포함되어 있으며, 소스 코드는 [GitHub 저장소](https://github.com/Osiris-DevWorks/smart-citizen)에서 제공됩니다.

관련 법률에서 요구하거나 서면으로 합의하지 않는 한, 이 라이선스에 따라 배포되는 소프트웨어는 명시적이든 묵시적이든 **어떠한 종류의 보증이나 조건 없이 "있는 그대로" 제공됩니다**. 권한과 제한 사항에 대한 구체적인 내용은 라이선스를 참조하세요.

## 번들로 포함된 타사 소프트웨어

Smart Citizen은 설치 프로그램 안에 다음 타사 소프트웨어를 포함하여 제공합니다. 각각의 전체 저작권 표시는 실행 파일 옆의 `NOTICE` 파일에 있습니다.

- **unp4k / unforge** — `assets/unp4k/`에 `unp4k.exe`와 `unforge.exe`로 포함되어 있습니다. Osiris DevWorks는 병렬 추출 및 성능 개선이 더해진, 원본 [dolkensp/unp4k](https://github.com/dolkensp/unp4k) 프로젝트의 자체 포크([odw-fast-unp4k](https://github.com/Osiris-DevWorks/odw-fast-unp4k))를 제공합니다. `Data.p4k`를 압축 해제하고 DataForge 엔터티 파일을 XML로 변환하는 데 사용됩니다. **MIT 라이선스**에 따라 라이선스가 부여됩니다.
- **PyQt6** — Riverbank Computing의 UI 프레임워크입니다. 비상업적 배포에는 **GNU General Public License v3(GPL-3.0)**에 따라 사용되며, Riverbank로부터 상업용 라이선스도 제공됩니다. Smart Citizen은 무료 오픈 소스 커뮤니티 도구이며 GPL-3.0 조건에 해당합니다.
- **lxml** — lxml.de의 XML 파싱 라이브러리입니다. **BSD-3-Clause 라이선스**에 따라 사용됩니다.

Python 표준 라이브러리와 PyInstaller가 번들로 포함하는 기타 런타임 종속성은 자체 라이선스를 가지고 있습니다. [docs.python.org/3/license.html](https://docs.python.org/3/license.html)의 Python Software Foundation 라이선스를 참조하세요.

## 개인정보 및 데이터 처리

Smart Citizen은 **로컬 데스크톱 애플리케이션**입니다. 편집 내용, `user.ini`, `base.ini`, 사용자 지정 내용, 또는 컴퓨터의 다른 어떤 콘텐츠도 Osiris DevWorks나 제3자가 운영하는 서버로 전송하지 않습니다.

### 컴퓨터에 남는 것

모든 것입니다. 현지화 편집 내용, 백업, 애플리케이션 설정, DataForge 캐시는 오직 로컬 디스크에만 존재합니다:

- **설정** — 기본 설치에서는 `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen` 아래의 Windows 레지스트리, 휴대용 버전에서는 실행 파일 옆의 `config.json`.
- **사용자 편집 내용 + 백업** — 기본적으로 `Documents\Smart Citizen\{채널}\`(설정 탭에서 사용자 지정 가능; 휴대용 버전은 대신 `<실행 파일 디렉터리>\data\`를 사용).
- **DataForge XML 캐시** — `%LOCALAPPDATA%\Smart Citizen\{채널}\cache\dataforge\`.
- **충돌 덤프 + 수동 로그 내보내기** — `Documents\Smart Citizen\logs\`(또는 휴대용 버전에서 동일한 위치). 앱이 충돌하거나 로그 탭에서 *내보내기*를 클릭할 때만 작성됩니다.

### 네트워크로 전송되는 것

Smart Citizen은 다음 세 가지 상황에서만 외부로 나가는 네트워크 요청을 보냅니다:

- **업데이트 확인** — 설치된 버전을 최신 GitHub 릴리스와 비교하기 위해 약 6시간마다 `api.github.com/repos/Osiris-DevWorks/smart-citizen/releases/latest`로 작은 인증 없는 요청을 보냅니다. 릴리스 메타데이터(태그 이름, 릴리스 URL)만 반환되며, Smart Citizen 상태는 전송되지 않습니다.
- **언어 다운로드** — 영어가 아닌 언어로 전환하면, Smart Citizen이 구성된 URL에서 해당 언어의 커뮤니티 번역 `global.ini`를 다운로드합니다(기본값은 [Dymerz/StarCitizen-Localization](https://github.com/Dymerz/StarCitizen-Localization) GitHub 저장소). 다운로드는 로컬에 캐시되며, 컴퓨터에서 아무것도 전송되지 않습니다.
- **사용자 구성 원격 소스** — 설정 탭에서 `http(s)://` URL을 가리키는 데이터 소스를 구성한 경우, Smart Citizen은 소스 파일을 새로 고칠 때 해당 URL을 가져옵니다. 기본 설정에서는 이는 `global` 소스의 GitHub-raw URL 형태에만 적용되며, v1.0부터 표준 구성은 대신 로컬 Data.p4k 추출에서 `base.ini`를 읽습니다.

### Smart Citizen이 **하지 않는** 것

- 어떤 종류의 텔레메트리, 분석, 사용 보고도 하지 않습니다.
- 개인 식별 정보를 수집, 저장, 전송하지 않습니다.
- 백그라운드 데이터 업로드를 하지 않습니다.
- 원격 서버로의 자동 충돌 보고를 하지 않습니다. 충돌 덤프는 `Documents\Smart Citizen\logs\` 아래에 **로컬로만** 작성됩니다. 버그 보고서를 위해 공유하고 싶다면 파일을 직접 복사해 붙여 넣으면 됩니다.
- 계정, 로그인, 원격 신원이 없습니다.

위와 상충되는 동작을 발견하면 [github.com/Osiris-DevWorks/smart-citizen/issues](https://github.com/Osiris-DevWorks/smart-citizen/issues)에 버그 보고서를 제출해 주세요.

## AI 사용 성명

Smart Citizen 소스 코드의 일부는 Anthropic의 AI 코딩 어시스턴트인 **Claude**의 도움으로 작성되었습니다. 생성된 코드는 병합되기 전에 **인간 관리자가 검토하고 승인**합니다. AI는 직접 커밋하지 않으며, 다른 모든 코드 기여와 동일하게 취급됩니다: 오직 그 자체의 가치로만 읽고, 테스트하고, 수용합니다.

구체적으로:

- AI 지원은 생성기, 분류기, 리팩터링, 테스트의 개발을 가속화합니다. AI 도움으로 작성된 커밋은 커밋 메시지에 `Co-Authored-By: Claude` 트레일러를 포함하여 이력을 감사할 수 있게 합니다.
- 모든 Star Citizen 게임 데이터 파싱 로직, 임무 분류, 텍스트 처리 규칙은 인간 관리자가 설계하며 실제 DataForge 캐시 샘플을 기준으로 검증합니다.
- Smart Citizen의 인터페이스 및 문서 번역 중 일부는 인간 번역이 도착할 때까지 AI가 임시로 생성합니다. 이는 `languages/TRANSLATIONS.md`에 언어별, 텍스트별로 추적되며, 인간 번역이 도착하면 교체됩니다. 기존 인간 번역은 AI가 절대 수정하지 않습니다.
- **애플리케이션 자체에는 AI나 머신러닝 기능이 전혀 포함되어 있지 않습니다.** Smart Citizen은 어떤 모델도 번들로 포함하지 않으며, 실행 시 어떤 AI 서비스도 호출하지 않고, 편집 내용이나 Star Citizen 게임 데이터를 AI 제공업체로 전송하지 않습니다.

## 법적 문제 신고

Smart Citizen이 귀하가 보유한 저작권, 상표, 또는 기타 권리를 침해한다고 생각되거나, 앱이 데이터를 어떻게 처리하는지에 대한 질문이 있으시면, issue를 열거나 [Osiris DevWorks Discord](https://discord.gg/BNzRegKZ7k)를 통해 관리자에게 연락하세요.
