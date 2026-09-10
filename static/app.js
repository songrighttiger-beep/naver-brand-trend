let searchResults = null;
let searchBrands = null;
let searchAnchor = null;
let searchParams = null;
let progressTimer = null;

function saveApiKey() {
    const clientId = document.getElementById('clientId').value.trim();
    const clientSecret = document.getElementById('clientSecret').value.trim();
    if (!clientId || !clientSecret) { alert('请输入API密钥。'); return; }
    if (clientId.length < 5 || clientSecret.length < 5) { alert('API密钥长度不足。'); return; }
    localStorage.setItem('naverClientId', clientId);
    localStorage.setItem('naverClientSecret', clientSecret);
    document.getElementById('apiSaved').style.display = 'inline';
    setTimeout(() => { document.getElementById('apiSaved').style.display = 'none'; }, 2000);
}

function loadApiKey() {
    const savedId = localStorage.getItem('naverClientId');
    const savedSecret = localStorage.getItem('naverClientSecret');
    if (savedId && savedId.length > 5) document.getElementById('clientId').value = savedId;
    if (savedSecret && savedSecret.length > 5) document.getElementById('clientSecret').value = savedSecret;
}

function uploadBrands(input) {
    if (!input.files.length) return;
    const file = input.files[0];
    const formData = new FormData();
    formData.append('file', file);
    fetch('/api/upload-brands', { method: 'POST', body: formData })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                document.getElementById('uploadResult').innerHTML = `<span style="color:#e74c3c">${data.error}</span>`;
            } else {
                document.getElementById('brands').value = data.brands.join('\n');
                document.getElementById('uploadResult').innerHTML = `<span style="color:#03c75a">已加载${data.count}个品牌</span>`;
                updateBrandCount();
            }
        })
        .catch(err => {
            document.getElementById('uploadResult').innerHTML = `<span style="color:#e74c3c">上传错误: ${err}</span>`;
        });
}

function updateBrandCount() {
    const textarea = document.getElementById('brands');
    const lines = textarea.value.split('\n').filter(l => l.trim());
    document.getElementById('brandCountInfo').textContent = `共${lines.length}个品牌`;
    updateApiEstimate(lines.length);
}

function updateApiEstimate(brandCount) {
    if (brandCount === 0) {
        document.getElementById('apiEstimate').classList.remove('show');
        return;
    }
    const nonAnchor = Math.max(brandCount - 1, 0);
    const totalCalls = Math.ceil(nonAnchor / 4);
    const warning = totalCalls > 1000 ? '<span class="warning">超出额度！</span>' : '';
    document.getElementById('apiEstimate').innerHTML =
        `预计API调用：约<strong>${totalCalls}次</strong>（${brandCount}个品牌，每次处理4个）${warning}`;
    document.getElementById('apiEstimate').classList.add('show');
}

function previewKeywords() {
    const brandsText = document.getElementById('brands').value.trim();
    if (!brandsText) { alert('请先输入品牌。'); return; }
    fetch('/api/preview-keywords', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ brands: brandsText })
    })
    .then(r => r.json())
    .then(data => {
        const previewDiv = document.getElementById('keywordPreview');
        let html = `<div style="margin-bottom:8px;font-size:13px;color:#636e72">共${data.total}个品牌，前${Object.keys(data.preview).length}个预览：</div>`;
        html += '<table class="keyword-table"><thead><tr><th>品牌</th><th>自动生成关键词</th></tr></thead><tbody>';
        for (const [brand, keywords] of Object.entries(data.preview)) {
            html += `<tr><td><strong>${brand}</strong></td><td>${keywords.join('、')}</td></tr>`;
        }
        html += '</tbody></table>';
        previewDiv.innerHTML = html;
    })
    .catch(err => { alert(`预览错误: ${err}`); });
}

function startSearch() {
    const clientId = document.getElementById('clientId').value.trim();
    const clientSecret = document.getElementById('clientSecret').value.trim();
    const brandsText = document.getElementById('brands').value.trim();
    const anchor = document.getElementById('anchor').value.trim();
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    const timeUnit = document.querySelector('input[name="timeUnit"]:checked').value;

    if (!clientId || !clientSecret) { alert('请输入API密钥。'); return; }
    if (!brandsText) { alert('请输入品牌。'); return; }
    if (!anchor) { alert('请输入锚点品牌。'); return; }
    if (!startDate || !endDate) { alert('请设置查询期间。'); return; }

    const brands = brandsText.split('\n').map(b => b.trim()).filter(b => b);
    searchBrands = brands;
    searchAnchor = anchor;
    searchParams = { startDate, endDate, timeUnit };

    const btn = document.getElementById('searchBtn');
    btn.disabled = true;
    btn.textContent = '查询中...';

    document.getElementById('progressCard').style.display = 'block';
    document.getElementById('errorCard').style.display = 'none';
    document.getElementById('resultsCard').style.display = 'none';

    if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }

    fetch('/api/search', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clientId, clientSecret, brands: brandsText, anchor, startDate, endDate, timeUnit })
    })
    .then(r => r.json())
    .then(data => {
        if (data.error) {
            showError(data.error);
            btn.disabled = false;
            btn.textContent = '开始趋势查询';
        } else {
            pollProgress(data.taskId);
        }
    })
    .catch(err => {
        showError(`错误: ${err}`);
        btn.disabled = false;
        btn.textContent = '开始趋势查询';
    });
}

function pollProgress(taskId) {
    progressTimer = setInterval(() => {
        fetch(`/api/progress/${taskId}`)
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    clearInterval(progressTimer); progressTimer = null;
                    showError(data.error);
                    document.getElementById('searchBtn').disabled = false;
                    document.getElementById('searchBtn').textContent = '开始趋势查询';
                    return;
                }

                const pct = data.total > 0 ? (data.current / data.total * 100) : 0;
                document.getElementById('progressBar').style.width = pct + '%';
                document.getElementById('progressText').textContent = data.message;
                document.getElementById('apiCounter').textContent = `API调用: ${data.current}/${data.total}次 (每日额度1,000次)`;

                if (data.status === 'completed') {
                    clearInterval(progressTimer); progressTimer = null;
                    displayResults(data.results, data.api_calls);
                    document.getElementById('searchBtn').disabled = false;
                    document.getElementById('searchBtn').textContent = '开始趋势查询';
                } else if (data.status === 'error') {
                    clearInterval(progressTimer); progressTimer = null;
                    showError(data.message);
                    document.getElementById('searchBtn').disabled = false;
                    document.getElementById('searchBtn').textContent = '开始趋势查询';
                }
            })
            .catch(err => {
                clearInterval(progressTimer); progressTimer = null;
                showError(`进度查询错误: ${err}`);
                document.getElementById('searchBtn').disabled = false;
                document.getElementById('searchBtn').textContent = '开始趋势查询';
            });
    }, 300);
}

function showError(msg) {
    document.getElementById('errorCard').style.display = 'block';
    document.getElementById('errorMessage').textContent = msg;
}

function displayResults(results, apiCalls) {
    searchResults = results;
    document.getElementById('progressCard').style.display = 'none';
    document.getElementById('resultsCard').style.display = 'block';

    const brandData = [];
    for (const brand of searchBrands) {
        if (results[brand]) {
            const ratios = results[brand].map(d => d.ratio);
            const avg = ratios.reduce((a, b) => a + b, 0) / ratios.length;
            brandData.push({ brand, avg: Math.round(avg * 100) / 100, max: Math.max(...ratios), data: results[brand] });
        }
    }
    brandData.sort((a, b) => b.avg - a.avg);

    const periods = brandData.length > 0 ? brandData[0].data.map(d => d.period) : [];

    let headerHtml = '<th>排名</th><th>品牌</th><th>平均</th><th>最大</th>';
    periods.forEach(p => { headerHtml += `<th>${p}</th>`; });
    document.getElementById('tableHeader').innerHTML = headerHtml;

    let bodyHtml = '';
    brandData.forEach((item, i) => {
        bodyHtml += `<tr><td>${i + 1}</td><td>${item.brand}</td><td><strong>${item.avg}</strong></td><td>${item.max}</td>`;
        item.data.forEach(d => { bodyHtml += `<td>${d.ratio}</td>`; });
        bodyHtml += '</tr>';
    });
    document.getElementById('tableBody').innerHTML = bodyHtml;
}

function downloadExcel() {
    if (!searchResults || !searchBrands || !searchParams) return;
    fetch('/api/export', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ results: searchResults, brands: searchBrands, anchor: searchAnchor, ...searchParams })
    })
    .then(r => r.blob())
    .then(blob => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `naver_trend_${searchParams.startDate}_${searchParams.endDate}.xlsx`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    })
    .catch(err => alert(`下载错误: ${err}`));
}

function getLocalDateStr(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

function updateQuota() {
    fetch('/api/quota')
        .then(r => r.json())
        .then(data => {
            const bar = document.getElementById('apiQuotaBar');
            const progress = document.getElementById('quotaProgress');
            const numbers = document.getElementById('quotaNumbers');
            const detail = document.getElementById('quotaDetail');

            const pct = data.percent;
            progress.style.width = pct + '%';

            bar.classList.remove('warning', 'danger');
            progress.classList.remove('warning', 'danger');
            numbers.classList.remove('warning', 'danger');

            if (data.level === 'yellow') {
                bar.classList.add('warning');
                progress.classList.add('warning');
                numbers.classList.add('warning');
            } else if (data.level === 'red') {
                bar.classList.add('danger');
                progress.classList.add('danger');
                numbers.classList.add('danger');
            }

            numbers.textContent = `${data.used} / ${data.total} (${pct}%)`;
            detail.textContent = `剩余 ${data.remaining} 次 | 超过1000次需付费 (约0.5韩元/次)`;
        })
        .catch(err => {
            document.getElementById('quotaNumbers').textContent = '获取失败';
        });
}

document.addEventListener('DOMContentLoaded', () => {
    loadApiKey();
    document.getElementById('brands').addEventListener('input', updateBrandCount);

    const today = new Date();
    const sixMonthsAgo = new Date(today);
    sixMonthsAgo.setMonth(sixMonthsAgo.getMonth() - 6);
    document.getElementById('startDate').value = getLocalDateStr(sixMonthsAgo);
    document.getElementById('endDate').value = getLocalDateStr(today);

    document.getElementById('brands').value = 'musinsa\nWconcept\nchancechance\nAttrangs\nLapla\nGlowny\nSo-ir\nBodyblue\nLinavenue\nClote';
    updateBrandCount();
    updateQuota();
    setInterval(updateQuota, 10000);
});
