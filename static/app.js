/**
 * AI Data Insight Builder - Frontend Logic (Vanilla JS)
 * Chart.js 시각화 및 백엔드 REST API 비동기 통신
 */

document.addEventListener("DOMContentLoaded", () => {
  console.log("[PAGE] 페이지 로드 완료");

  // 상태 관리 변수
  let currentChart = null;
  let currentMode = "B"; // 기본 정식 모드 B
  let lastSuggestedTool = null;
  let lastQueryResult = null; // 자연어 질의 최신 연산 결과

  // DOM 요소 참조
  const statusDot = document.getElementById("statusDot");
  const statusText = document.getElementById("statusText");

  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const inspectLoading = document.getElementById("inspectLoading");
  const inspectResult = document.getElementById("inspectResult");

  const diagFilename = document.getElementById("diagFilename");
  const diagEncoding = document.getElementById("diagEncoding");
  const diagShape = document.getElementById("diagShape");
  const diagRecYear = document.getElementById("diagRecYear");
  const diagWarningsBox = document.getElementById("diagWarningsBox");
  const diagWarningsList = document.getElementById("diagWarningsList");
  const previewTable = document.getElementById("previewTable");

  const sectionSuggest = document.getElementById("sectionSuggest");
  const btnGetSuggestions = document.getElementById("btnGetSuggestions");
  const suggestLoading = document.getElementById("suggestLoading");
  const suggestionsList = document.getElementById("suggestionsList");

  // 자연어 질의 관련 DOM 요소
  const nlPromptChips = document.getElementById("nlPromptChips");
  const nlQueryInput = document.getElementById("nlQueryInput");
  const btnSubmitQuery = document.getElementById("btnSubmitQuery");
  const nlQueryLoading = document.getElementById("nlQueryLoading");
  const nlAnswerCard = document.getElementById("nlAnswerCard");
  const nlAnswerQueryText = document.getElementById("nlAnswerQueryText");
  const nlAnswerToolTag = document.getElementById("nlAnswerToolTag");
  const nlAnswerContent = document.getElementById("nlAnswerContent");
  const btnVisualizeQuery = document.getElementById("btnVisualizeQuery");

  const sectionRun = document.getElementById("sectionRun");
  const runLoading = document.getElementById("runLoading");
  const metaToolName = document.getElementById("metaToolName");
  const metaRefPeriod = document.getElementById("metaRefPeriod");
  const metaRowsUsed = document.getElementById("metaRowsUsed");
  const metaRowsExcluded = document.getElementById("metaRowsExcluded");
  const calcResultDisplay = document.getElementById("calcResultDisplay");
  const chartItemCountBadge = document.getElementById("chartItemCountBadge");
  const chartUnitBadge = document.getElementById("chartUnitBadge");
  const chartWrapper = document.getElementById("chartWrapper");
  const chartScrollWrapper = document.getElementById("chartScrollWrapper");

  const sectionExplain = document.getElementById("sectionExplain");
  const tabModeB = document.getElementById("tabModeB");
  const tabModeA = document.getElementById("tabModeA");
  const btnExplain = document.getElementById("btnExplain");
  const explainLoading = document.getElementById("explainLoading");
  const reportContent = document.getElementById("reportContent");

  // ==========================================================================
  // 0. 서버 상태 확인 (GET /health)
  // ==========================================================================
  async function checkServerHealth() {
    try {
      const res = await fetch("/health");
      const data = await res.json();
      if (res.ok && data.status === "ok") {
        statusDot.className = "status-dot online";
        statusText.textContent = `연결됨 (${data.model})`;
      } else {
        throw new Error("서버 비정상 상태");
      }
    } catch (err) {
      statusDot.className = "status-dot offline";
      statusText.textContent = "서버 연결 불가";
      console.error("[ERROR] 헬스체크 실패:", err.message);
    }
  }
  checkServerHealth();

  // ==========================================================================
  // 1. CSV 파일 업로드 및 진단 (POST /inspect)
  // ==========================================================================
  dropzone.addEventListener("click", () => fileInput.click());

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      handleFileUpload(e.target.files[0]);
    }
  });

  async function handleFileUpload(file) {
    if (!file.name.toLowerCase().endsWith(".csv")) {
      alert("CSV 파일(.csv)만 업로드할 수 있습니다.");
      return;
    }

    console.log("[UPLOAD] 파일 선택", { name: file.name, size: `${(file.size / 1024).toFixed(1)} KB` });

    const formData = new FormData();
    formData.append("file", file);

    inspectLoading.classList.remove("hidden");
    inspectResult.classList.add("hidden");
    sectionSuggest.classList.add("hidden");
    sectionRun.classList.add("hidden");
    sectionExplain.classList.add("hidden");

    try {
      console.log("[INSPECT] 진단 요청 시작");
      const res = await fetch("/inspect", {
        method: "POST",
        body: formData
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "파일 진단 중 오류가 발생했습니다.");
      }

      console.log("[INSPECT] 응답 수신", {
        rows: data.rows,
        columns: data.columns,
        warnings: data.warnings ? data.warnings.length : 0
      });

      // 진단 메트릭 표시
      diagFilename.textContent = `${data.filename} (${(data.file_size / 1024).toFixed(1)} KB)`;
      diagEncoding.textContent = `${data.encoding} (헤더 앞 ${data.skipped_rows}줄 건너뜀)`;
      diagShape.textContent = `${data.rows.toLocaleString()}행 × ${data.columns}열`;
      diagRecYear.textContent = data.recommended_year ? `${data.recommended_year}년` : "연도 열 없음";

      // 경고 목록 표시
      if (data.warnings && data.warnings.length > 0) {
        diagWarningsList.innerHTML = "";
        data.warnings.forEach((w) => {
          const li = document.createElement("li");
          li.textContent = w;
          diagWarningsList.appendChild(li);
        });
        diagWarningsBox.classList.remove("hidden");
      } else {
        diagWarningsBox.classList.add("hidden");
      }

      // 10행 미리보기 테이블 생성
      renderPreviewTable(data.column_names, data.preview);

      inspectResult.classList.remove("hidden");
      sectionSuggest.classList.remove("hidden");

    } catch (err) {
      console.error("[ERROR] 진단 오류:", err.message);
      alert(`[진단 오류] ${err.message}`);
    } finally {
      inspectLoading.classList.add("hidden");
    }
  }

  function renderPreviewTable(columns, previewRows) {
    if (!previewRows || previewRows.length === 0) return;
    previewTable.innerHTML = "";

    // 헤더 행
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    columns.forEach((col) => {
      const th = document.createElement("th");
      th.textContent = col;
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    previewTable.appendChild(thead);

    // 본문 행 (최대 10행)
    const tbody = document.createElement("tbody");
    previewRows.forEach((row) => {
      const tr = document.createElement("tr");
      columns.forEach((col) => {
        const td = document.createElement("td");
        const val = row[col];
        td.textContent = (val === null || val === undefined) ? "" : String(val);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    previewTable.appendChild(tbody);
  }

  // ==========================================================================
  // 2-A. 자연어 질의 처리 (POST /query)
  // ==========================================================================
  if (btnSubmitQuery) {
    btnSubmitQuery.addEventListener("click", () => {
      const q = nlQueryInput.value.trim();
      if (q) executeNaturalQuery(q);
    });
  }

  if (nlQueryInput) {
    nlQueryInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const q = nlQueryInput.value.trim();
        if (q) executeNaturalQuery(q);
      }
    });
  }

  if (nlPromptChips) {
    nlPromptChips.addEventListener("click", (e) => {
      const chip = e.target.closest(".chip-btn");
      if (chip && chip.dataset.query) {
        nlQueryInput.value = chip.dataset.query;
        executeNaturalQuery(chip.dataset.query);
      }
    });
  }

  async function executeNaturalQuery(userQuery) {
    console.log("[QUERY] 자연어 질문 요청 시작", { query: userQuery });
    nlQueryLoading.classList.remove("hidden");
    nlAnswerCard.classList.add("hidden");

    try {
      const res = await fetch("/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: userQuery })
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "질문 처리 중 오류가 발생했습니다.");
      }

      console.log("[QUERY] 자연어 질문 응답 수신", {
        tool: data.tool,
        tool_ko: data.tool_name_ko,
        rows_used: data.result ? data.result.rows_used : 0
      });

      lastQueryResult = data;

      nlAnswerQueryText.textContent = data.query;
      nlAnswerToolTag.textContent = `${data.tool_name_ko} (${data.tool})`;
      nlAnswerContent.innerHTML = window.marked ? marked.parse(data.answer) : data.answer;
      nlAnswerCard.classList.remove("hidden");

      setTimeout(() => {
        nlAnswerCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }, 50);

    } catch (err) {
      console.error("[ERROR] 자연어 질의 오류:", err.message);
      alert(`[질문 분석 오류] ${err.message}`);
    } finally {
      nlQueryLoading.classList.add("hidden");
    }
  }

  // ==========================================================================
  // 2-B. 자연어 질의 결과 시각화 버튼 (차트 및 Step 3/4 전환)
  // ==========================================================================
  if (btnVisualizeQuery) {
    btnVisualizeQuery.addEventListener("click", () => {
      if (!lastQueryResult || !lastQueryResult.result) {
        alert("시각화할 질문 분석 결과가 없습니다.");
        return;
      }

      console.log("[VISUALIZE] 자연어 질의 결과 차트 시각화 전환", {
        tool: lastQueryResult.tool
      });

      const d = lastQueryResult.result;
      const toolNameKo = lastQueryResult.tool_name_ko || lastQueryResult.tool;

      // 1. 먼저 Step 3 및 Step 4 영역을 화면에 표시 (Canvas 크기 정상 계산용)
      sectionRun.classList.remove("hidden");
      sectionExplain.classList.remove("hidden");

      // 2. Step 3 메타데이터 채우기
      metaToolName.textContent = `${toolNameKo} (${lastQueryResult.tool})`;
      metaRefPeriod.textContent = d.reference_period || (lastQueryResult.params && lastQueryResult.params.reference_period) || "기준 시점";
      metaRowsUsed.textContent = `${(d.rows_used || 0).toLocaleString()}개 항목 (정상 계산)`;
      metaRowsExcluded.textContent = `${d.rows_excluded || 0}개 항목 (${d.exclusion_reason || "미해당"})`;

      // 3. 차트 데이터 추출 (d.result.chart_data 또는 d.chart_data)
      const chartData = (d.result && d.result.chart_data) ? d.result.chart_data : d.chart_data;

      // 4. Chart.js 렌더링
      if (chartData) {
        renderChart(chartData, lastQueryResult.unit || d.unit);
      } else {
        destroyChart();
      }

      // 5. 수치 요약 테이블 렌더링
      renderResultSummary(d);

      // 6. Step 3으로 부드럽게 스크롤
      setTimeout(() => {
        sectionRun.scrollIntoView({ behavior: "smooth" });
      }, 50);
    });
  }

  // ==========================================================================
  // 2-C. Gemini 분석 제안 (POST /suggest)
  // ==========================================================================
  btnGetSuggestions.addEventListener("click", fetchSuggestions);

  async function fetchSuggestions() {
    suggestLoading.classList.remove("hidden");
    suggestionsList.innerHTML = "";

    try {
      console.log("[SUGGEST] 제안 요청 시작");
      const res = await fetch("/suggest", { method: "POST" });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "제안 요청에 실패했습니다.");
      }

      const suggestions = data.suggestions || [];
      console.log("[SUGGEST] 응답 수신", { count: suggestions.length });

      if (suggestions.length === 0) {
        suggestionsList.innerHTML = "<p>실행 가능한 제안이 없습니다.</p>";
        return;
      }

      // 제안 카드 목록 렌더링
      suggestionsList.innerHTML = "";
      suggestions.forEach((s) => {
        const card = document.createElement("div");
        card.className = "suggestion-card";

        const badge = document.createElement("span");
        badge.className = "tool-badge";
        badge.textContent = s.tool;

        const why = document.createElement("p");
        why.className = "why-text";
        why.textContent = s.why;

        const caution = document.createElement("p");
        caution.className = "caution-text";
        caution.textContent = `주의: ${s.caution}`;

        const btnRun = document.createElement("button");
        btnRun.className = "btn btn-primary btn-sm";
        btnRun.textContent = "이 분석 실행하기";
        btnRun.addEventListener("click", () => {
          lastSuggestedTool = s;
          executeToolRun(s.tool, s.params);
        });

        card.appendChild(badge);
        card.appendChild(why);
        card.appendChild(caution);
        card.appendChild(btnRun);
        suggestionsList.appendChild(card);
      });

    } catch (err) {
      console.error("[ERROR] 제안 오류:", err.message);
      alert(`[제안 오류] ${err.message}`);
    } finally {
      suggestLoading.classList.add("hidden");
    }
  }

  // ==========================================================================
  // 3. Pandas 도구 실행 및 차트 렌더링 (POST /run)
  // ==========================================================================
  async function executeToolRun(toolName, params) {
    const refPeriod = params.reference_period || "단일/전체 시점";
    console.log("[RUN] 도구 실행 시작", { tool: toolName, reference_period: refPeriod });

    sectionRun.classList.remove("hidden");
    runLoading.classList.remove("hidden");
    calcResultDisplay.innerHTML = "";
    reportContent.classList.add("hidden");

    // 섹션 3으로 스크롤 이동
    sectionRun.scrollIntoView({ behavior: "smooth" });

    try {
      const res = await fetch("/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool: toolName, params: params })
      });
      const respData = await res.json();

      if (!res.ok) {
        throw new Error(respData.error || "분석 실행에 실패했습니다.");
      }

      const d = respData.data;
      console.log("[RUN] 결과 수신", { rows_used: d.rows_used, rows_excluded: d.rows_excluded });

      // 실행 메타데이터 카드 표시
      metaToolName.textContent = d.tool;
      metaRefPeriod.textContent = d.reference_period;
      metaRowsUsed.textContent = `${d.rows_used.toLocaleString()}개 항목 (정상 계산)`;
      metaRowsExcluded.textContent = `${d.rows_excluded}개 항목 (${d.exclusion_reason})`;

      // Chart.js 시각화 렌더링
      if (d.result && d.result.chart_data) {
        renderChart(d.result.chart_data, d.unit);
      } else {
        destroyChart();
      }

      // 수치 결과 테이블/요약 렌더링
      renderResultSummary(d);

      // Step 4(해석 섹션) 활성화
      sectionExplain.classList.remove("hidden");

    } catch (err) {
      console.error("[ERROR] 실행 오류:", err.message);
      alert(`[실행 오류] ${err.message}`);
    } finally {
      runLoading.classList.add("hidden");
    }
  }

  function destroyChart() {
    if (currentChart) {
      currentChart.destroy();
      currentChart = null;
    }
  }

  function renderChart(chartData, unit) {
    destroyChart();
    const ctx = document.getElementById("insightChart").getContext("2d");
    const chartType = chartData.type || "bar";
    const isHorizontal = !!chartData.horizontal;
    const labelCount = (chartData.labels || []).length;

    // 상단 뱃지 갱신
    if (chartItemCountBadge) {
      chartItemCountBadge.textContent = labelCount > 0 ? `총 ${labelCount}개 항목 표시` : "데이터 없음";
    }
    if (chartUnitBadge) {
      chartUnitBadge.textContent = `단위: ${unit || "%"}`;
    }

    // 가로 막대 그래프인 경우 데이터 개수에 비례하여 캔버스 높이를 동적으로 확장 (가시성 극대화)
    if (chartWrapper) {
      if (isHorizontal) {
        // 항목당 최소 30px의 높이 확보 (30개 항목이면 약 980px 확보)
        const dynamicHeight = Math.max(380, labelCount * 30 + 80);
        chartWrapper.style.height = `${dynamicHeight}px`;
      } else {
        chartWrapper.style.height = "420px";
      }
    }

    let chartConfig = {
      type: chartType,
      data: {},
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: {
          padding: { top: 15, right: 25, bottom: 15, left: 10 }
        },
        plugins: {
          legend: {
            display: chartType === "line" || chartType === "scatter",
            position: "top",
            labels: {
              boxWidth: 12,
              font: { family: "Pretendard, system-ui, sans-serif", size: 12, weight: 600 }
            }
          },
          tooltip: {
            backgroundColor: "rgba(15, 23, 42, 0.9)",
            padding: 10,
            titleFont: { size: 13, weight: 700 },
            bodyFont: { size: 12 },
            cornerRadius: 8,
            callbacks: {
              label: (context) => {
                const val = context.parsed.y !== undefined && !isHorizontal ? context.parsed.y : context.parsed.x;
                const displayVal = val !== undefined ? val : context.raw;
                return ` ${context.dataset.label || "값"}: ${displayVal} ${unit || ""}`;
              }
            }
          }
        },
        scales: {
          x: {
            grid: { color: "#f1f5f9" },
            ticks: {
              autoSkip: !isHorizontal, // 가로 막대일 때는 수치 축이므로 autoSkip 허용
              font: { family: "Pretendard, system-ui, sans-serif", size: 11, weight: 500 },
              color: "#64748b"
            }
          },
          y: {
            grid: { color: "#f8fafc" },
            ticks: {
              // 중요: 가로 막대일 때 Y축 레이블(국가명)이 절대 건너뛰어지지 않도록 autoSkip을 false로 강제!
              autoSkip: isHorizontal ? false : true,
              font: {
                family: "Pretendard, system-ui, sans-serif",
                size: isHorizontal && labelCount > 20 ? 11 : 12,
                weight: 600
              },
              color: "#1e293b",
              padding: 8
            }
          }
        }
      }
    };

    if (isHorizontal) {
      chartConfig.options.indexAxis = "y";
    }

    if (chartType === "line" || chartType === "scatter") {
      chartConfig.data = {
        labels: chartData.labels || [],
        datasets: (chartData.datasets || []).map((ds, idx) => ({
          label: ds.label,
          data: ds.data,
          borderColor: ["#2563eb", "#7c3aed", "#059669", "#d97706", "#dc2626", "#0284c7"][idx % 6],
          backgroundColor: ["#2563eb", "#7c3aed", "#059669", "#d97706", "#dc2626", "#0284c7"][idx % 6],
          tension: 0.25,
          borderWidth: 2.5,
          pointRadius: 4,
          pointHoverRadius: 6
        }))
      };
    } else {
      // 일반 막대 차트 (단일 데이터셋)
      // 1) 막대별 개별 무지개 선형 그라데이션 (각 막대 내부 왼쪽->오른쪽)
      // 2) 전체 순위 1위->N위: 무지개 색조 순환 (Hue 10°~310°)
      // 3) 순위별 채도 그라데이션: 상위권은 진하고 선명한 채도(92%), 하위권으로 갈수록 부드럽고 옅은 파스텔톤(48%)으로 유지
      const totalLabels = (chartData.labels || []).length;
      const highlightIdx = chartData.highlight_index !== undefined ? chartData.highlight_index : -1;

      const bgGradients = (chartData.labels || []).map((_, i) => {
        if (i === highlightIdx) {
          // 사용자 선택 강조 항목 (고급스러운 인디고-바이올렛 그라데이션)
          const g = isHorizontal
            ? ctx.createLinearGradient(0, 0, 700, 0)
            : ctx.createLinearGradient(0, 0, 0, 420);
          g.addColorStop(0, "rgba(124, 58, 237, 1)");
          g.addColorStop(1, "rgba(99, 102, 241, 0.85)");
          return g;
        }

        // 전체 순위에 따른 진행도 (0.0 ~ 1.0)
        const progress = totalLabels > 1 ? i / (totalLabels - 1) : 0;

        // [무지개 색조]: 빨강(10°) -> 주황(35°) -> 골드(50°) -> 에메랄드(145°) -> 틸(185°) -> 오션블루(220°) -> 퍼플(275°) -> 로즈(320°)
        const hue = Math.round((progress * 300 + 10) % 360);

        // [순위별 채도 그라데이션]: 1위 92% (가장 진함) -> 30위 48% (옅고 부드러움)
        const satStart = Math.round(92 - progress * 44);
        const satEnd = Math.max(28, satStart - 18);

        // [순위별 명도]: 1위 48% (또렷함) -> 30위 68% (밝고 투명감 있음)
        const lightStart = Math.round(48 + progress * 20);
        const lightEnd = Math.min(84, lightStart + 12);

        // 막대 내부의 선형 그라데이션 (시작: 진한 색 -> 끝: 부드럽고 옅은 색)
        const grad = isHorizontal
          ? ctx.createLinearGradient(0, 0, 750, 0)
          : ctx.createLinearGradient(0, 0, 0, 420);

        grad.addColorStop(0, `hsla(${hue}, ${satStart}%, ${lightStart}%, 0.95)`);
        grad.addColorStop(1, `hsla(${hue}, ${satEnd}%, ${lightEnd}%, 0.78)`);

        return grad;
      });

      // 테두리 색상도 조화롭게 무지개 톤으로 매칭
      const borderColors = (chartData.labels || []).map((_, i) => {
        if (i === highlightIdx) return "rgba(109, 40, 217, 1)";
        const progress = totalLabels > 1 ? i / (totalLabels - 1) : 0;
        const hue = Math.round((progress * 300 + 10) % 360);
        const sat = Math.round(85 - progress * 35);
        const light = Math.round(40 + progress * 15);
        return `hsla(${hue}, ${sat}%, ${light}%, 0.9)`;
      });

      chartConfig.data = {
        labels: chartData.labels || [],
        datasets: [{
          label: "지표 수치",
          data: chartData.values || [],
          backgroundColor: bgGradients,
          borderColor: borderColors,
          borderWidth: 1,
          borderRadius: 6,
          borderSkipped: false,
          barThickness: isHorizontal ? (labelCount > 20 ? 18 : 22) : undefined,
          maxBarThickness: 32
        }]
      };
    }

    currentChart = new Chart(ctx, chartConfig);
    console.log("[CHART] 차트 렌더 완료", { type: chartType, count: labelCount });
  }

  function renderResultSummary(data) {
    const r = data.result;
    if (!r) return;

    let html = "";

    // 1. 순위 데이터 (top_records 또는 bottom_records) - 명확한 랭킹 테이블 렌더링
    const records = r.top_records || r.bottom_records;
    if (records && Array.isArray(records) && records.length > 0) {
      const modeTitle = r.mode === "bottom" ? "하위 순위 목록" : "상위 순위 목록";
      html += `
        <div class="ranking-table-container" style="margin-top: 0.5rem;">
          <div class="ranking-table-wrapper">
            <table class="ranking-table">
              <thead>
                <tr>
                  <th style="width: 70px; text-align: center;">순위</th>
                  <th>항목 / 국가명</th>
                  <th style="text-align: right; width: 150px;">지표 수치 (${data.unit || "%"})</th>
                </tr>
              </thead>
              <tbody>
                ${records.map((rec) => {
                  let badgeClass = "rank-badge";
                  if (rec.rank === 1) badgeClass += " rank-1";
                  else if (rec.rank === 2) badgeClass += " rank-2";
                  else if (rec.rank === 3) badgeClass += " rank-3";
                  return `
                    <tr>
                      <td style="text-align: center;"><span class="${badgeClass}">${rec.rank}</span></td>
                      <td><strong>${rec.label}</strong></td>
                      <td style="text-align: right;" class="rank-val">${rec.value !== null ? rec.value : "-"}</td>
                    </tr>
                  `;
                }).join("")}
              </tbody>
            </table>
          </div>
        </div>
      `;
    }

    // 2. 특정 1개 항목 vs 전체 비교 (compare_one_vs_all)
    if (r.target_item) {
      html += `
        <div class="metric-grid" style="margin-top: 0.5rem;">
          <div class="metric-card highlight">
            <span class="label">${r.target_item} 수치 / 순위</span>
            <span class="val">${r.target_value}${data.unit || "%"} (전체 ${r.total_count}개국 중 ${r.rank}위)</span>
          </div>
          <div class="metric-card">
            <span class="label">전체 백분위</span>
            <span class="val">상위 ${r.percentile}%</span>
          </div>
          <div class="metric-card">
            <span class="label">전체 중앙값 대비 격차</span>
            <span class="val" style="color:${r.diff_from_median >= 0 ? '#16a34a' : '#dc2626'};">
              ${r.diff_from_median >= 0 ? '+' : ''}${r.diff_from_median}%p
            </span>
          </div>
          <div class="metric-card">
            <span class="label">전체 평균 대비 격차</span>
            <span class="val" style="color:${r.diff_from_mean >= 0 ? '#16a34a' : '#dc2626'};">
              ${r.diff_from_mean >= 0 ? '+' : ''}${r.diff_from_mean}%p
            </span>
          </div>
        </div>
      `;
    }

    // 3. 통계 요약 (statistics)
    if (r.statistics) {
      html += `<div class="metric-grid" style="margin-top: 0.5rem;">
        <div class="metric-card"><span class="label">평균(Mean)</span><span class="val">${r.statistics.mean}</span></div>
        <div class="metric-card highlight"><span class="label">중앙값(Median)</span><span class="val">${r.statistics.median}</span></div>
        <div class="metric-card"><span class="label">최솟값 ~ 최댓값</span><span class="val">${r.statistics.min} ~ ${r.statistics.max}</span></div>
        <div class="metric-card"><span class="label">표준편차(Std)</span><span class="val">${r.statistics.std}</span></div>
      </div>`;
    } else if (r.correlation_coefficient !== undefined) {
      html += `<div class="alert-banner info" style="margin-top: 0.5rem;">
        <strong>피어슨 상관계수 (r):</strong> ${r.correlation_coefficient}
        <br><small>${data.cautions || ""}</small>
      </div>`;
    }

    calcResultDisplay.innerHTML = html;
  }

  // ==========================================================================
  // 4. Gemini 사실 기반 해석 리포트 (POST /explain)
  // ==========================================================================
  tabModeB.addEventListener("click", () => {
    currentMode = "B";
    tabModeB.classList.add("active");
    tabModeA.classList.remove("active");
  });

  tabModeA.addEventListener("click", () => {
    currentMode = "A";
    tabModeA.classList.add("active");
    tabModeB.classList.remove("active");
  });

  btnExplain.addEventListener("click", async () => {
    console.log("[EXPLAIN] 해석 요청 시작", { mode: currentMode });

    explainLoading.classList.remove("hidden");
    reportContent.classList.add("hidden");
    reportContent.innerHTML = "";

    try {
      const res = await fetch("/explain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: currentMode })
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "해석 보고서 생성에 실패했습니다.");
      }

      console.log("[EXPLAIN] 응답 수신");

      // Marked.js로 마크다운을 깔끔한 HTML로 변환
      if (window.marked && typeof marked.parse === "function") {
        reportContent.innerHTML = marked.parse(data.explanation);
      } else {
        reportContent.innerText = data.explanation;
      }

      reportContent.classList.remove("hidden");
      reportContent.scrollIntoView({ behavior: "smooth" });

      // 후속 질문 대화창 활성화 및 초기화
      initChatSection();

    } catch (err) {
      console.error("[ERROR] 해석 오류:", err.message);
      alert(`[해석 오류] ${err.message}`);
    } finally {
      explainLoading.classList.add("hidden");
    }
  });

  // ==========================================================================
  // 5. 후속 질문 대화창 (POST /chat)
  // ==========================================================================
  const chatSection = document.getElementById("chatSection");
  const chatChips = document.getElementById("chatChips");
  const chatMessages = document.getElementById("chatMessages");
  const chatLoading = document.getElementById("chatLoading");
  const chatForm = document.getElementById("chatForm");
  const chatInput = document.getElementById("chatInput");

  let chatHistory = [];

  function initChatSection() {
    chatSection.classList.remove("hidden");
    chatMessages.innerHTML = "";
    chatHistory = [];

    // 기본 추천 질문 목록 설정 ("쉽게 설명해줘" 반드시 포함)
    const initialQuestions = [
      "중학생도 이해할 수 있게 쉽게 설명해줘",
      "왜 1위 나라들은 100%에 도달했을까?",
      "여기서 제외된 항목들은 왜 빠진 거야?"
    ];
    renderChatChips(initialQuestions);
  }

  function renderChatChips(questions) {
    chatChips.innerHTML = "";
    
    // '쉽게 설명해줘' 관련 질문이 누락되지 않도록 필수 보장
    if (!questions.some(q => q.includes("쉽게"))) {
      questions.unshift("중학생도 이해할 수 있게 쉽게 설명해줘");
    }

    questions.forEach((q) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip-btn";
      btn.innerHTML = `💬 ${q}`;
      btn.addEventListener("click", () => {
        sendChatMessage(q);
      });
      chatChips.appendChild(btn);
    });
  }

  function appendChatMessage(sender, text) {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${sender}`;

    if (sender === "ai" && window.marked && typeof marked.parse === "function") {
      bubble.innerHTML = marked.parse(text);
    } else {
      bubble.textContent = text;
    }

    chatMessages.appendChild(bubble);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  async function sendChatMessage(userText) {
    if (!userText || userText.trim() === "") return;
    const cleanText = userText.trim();

    console.log("[CHAT] 후속 질문 전송:", cleanText);

    // 사용자 메시지 화면 출력 및 히스토리 추가
    appendChatMessage("user", cleanText);
    chatHistory.push({ role: "user", text: cleanText });

    chatLoading.classList.remove("hidden");

    try {
      const res = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: cleanText,
          history: chatHistory
        })
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "답변 생성에 실패했습니다.");
      }

      console.log("[CHAT] AI 응답 수신");

      // AI 답변 화면 출력 및 히스토리 추가
      appendChatMessage("ai", data.reply);
      chatHistory.push({ role: "model", text: data.reply });

      // 새로운 추천 질문 말풍선 갱신 ("쉽게 설명해줘" 가드레일 유지)
      if (data.suggested_questions && data.suggested_questions.length > 0) {
        renderChatChips(data.suggested_questions);
      }

    } catch (err) {
      console.error("[ERROR] 채팅 오류:", err.message);
      appendChatMessage("ai", `⚠️ 오류가 발생했습니다: ${err.message}`);
    } finally {
      chatLoading.classList.add("hidden");
    }
  }

  chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (text) {
      chatInput.value = "";
      sendChatMessage(text);
    }
  });

});
