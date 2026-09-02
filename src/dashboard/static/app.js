async function loadJobs() {
    const res = await fetch('/api/jobs');
    const data = await res.json();
    
    let html = `
        <h2>Recent Jobs</h2>
        <table>
            <thead>
                <tr>
                    <th>Company</th>
                    <th>Title</th>
                    <th>Score</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
    `;
    
    for (const job of data.jobs) {
        html += `
            <tr>
                <td>${job.company}</td>
                <td>${job.title}</td>
                <td>${job.match_score || '-'}</td>
                <td><span class="badge ${job.status}">${job.status}</span></td>
            </tr>
        `;
    }
    html += `</tbody></table>`;
    
    document.getElementById('main-content').innerHTML = html;
}

async function loadAnalytics() {
    const res = await fetch('/api/analytics/summary');
    const data = await res.json();
    
    document.getElementById('main-content').innerHTML = `
        <h2>Analytics</h2>
        <p>Total Applied: ${data.total_applied}</p>
        <p>Total Ghosted: ${data.total_ghosted}</p>
        <p>Avg Match Score: ${data.avg_match_score}</p>
    `;
}

// Load jobs on start
loadJobs();
