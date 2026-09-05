import { useEffect, useRef, useState } from 'react'
import { Background, Controls, ReactFlow } from '@xyflow/react'
import { Activity, ArrowUpRight, Check, CircleAlert, ShieldCheck, Sparkles, AlertTriangle, Menu, X, Clock } from 'lucide-react'
import dagre from 'dagre'
import '@xyflow/react/dist/style.css'
import './App.css'

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

const money = (paise = 0) => `Rs ${(paise / 100).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const time = (value) => new Date(value).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
const title = (value = '') => value.replaceAll('_', ' ')
const fetchJson = async (url, options) => {
  const response = await fetch(url, options)
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = payload.detail
    const msg = Array.isArray(detail)
      ? detail.map(e => `${e.loc?.slice(-1)[0] ?? ''}: ${e.msg}`).join('; ')
      : (typeof detail === 'string' ? detail : JSON.stringify(detail) || url)
    throw new Error(`${response.status} ${response.statusText}: ${msg}`)
  }
  return payload
}

function getLayoutedElements(nodes, edges) {
  const dagreGraph = new dagre.graphlib.Graph()
  dagreGraph.setDefaultEdgeLabel(() => ({}))
  const nodeWidth = 250
  const nodeHeight = 100
  dagreGraph.setGraph({ rankdir: 'LR', align: 'UL', ranksep: 80, nodesep: 50 })
  
  nodes.forEach((node) => { dagreGraph.setNode(node.id, { width: nodeWidth, height: nodeHeight }) })
  edges.forEach((edge) => { dagreGraph.setEdge(edge.source, edge.target) })
  
  dagre.layout(dagreGraph)
  
  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id)
    return {
      ...node,
      targetPosition: 'left',
      sourcePosition: 'right',
      position: {
        x: nodeWithPosition.x - nodeWidth / 2 + 140, // shift to accommodate the lane headers
        y: nodeWithPosition.y - nodeHeight / 2 + 40,
      }
    }
  })
  return { nodes: layoutedNodes, edges }
}

function App() {
  const [caseData, setCaseData] = useState(null)
  const [timeline, setTimeline] = useState([])
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [explanation, setExplanation] = useState(null)
  const [risk, setRisk] = useState(null)
  const [recommendation, setRecommendation] = useState(null)
  const [pendingCases, setPendingCases] = useState([])
  const [scenarioName, setScenarioName] = useState('')
  const [metrics, setMetrics] = useState({ open_cases: 0, exposure: 0, assured_cases: 0, total_cases: 0 })
  const [audit, setAudit] = useState([])
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(false)
  const [error, setError] = useState('')
  const [expandedSections, setExpandedSections] = useState({ timeline: false, audit: false })
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [addCaseDrawerOpen, setAddCaseDrawerOpen] = useState(false)
  const [learningDrawerOpen, setLearningDrawerOpen] = useState(false)
  const [learningStatus, setLearningStatus] = useState(null)
  const [leftView, setLeftView] = useState('graph')
  const [classifyMode, setClassifyMode] = useState(false)
  const [classification, setClassification] = useState({ violation_type: '', reason: '', recommended_action: '' })
  const hasLoadedCase = useRef(false)

  async function refreshMetrics() {
    setMetrics(await fetchJson(`${API}/assurance/metrics`))
  }

  async function loadCase(selectedScenario) {
    const analyzed = await fetchJson(`${API}/assurance/scenarios/${selectedScenario}`, { method: 'POST' })
    const selectedCase = (analyzed.cases || []).find((item) => item.violation_type !== 'UNCERTAIN_PAYMENT_CAPTURED') || (analyzed.cases || [])[0]
    
    setScenarioName(selectedScenario)
    setLeftView('graph')
    
    if (!selectedCase) {
      setCaseData({ case_id: 'C-NO-ISSUE', status: 'ASSURED', severity: 'NORMAL', financial_exposure: 0, violation_type: 'NO_VIOLATION', workflow: 'VERIFIED' })
      setTimeline([])
      setGraph({ nodes: [], edges: [] })
      setExplanation(null)
      setAudit([])
      setRisk(null)
      setRecommendation(null)
      return
    }

    setCaseData(selectedCase)
    const responses = await Promise.all(['timeline', 'graph', 'explanation', 'audit', 'risk', 'recommendation'].map((resource) => fetchJson(`${API}/assurance/cases/${selectedCase.case_id}/${resource}`)))
    setTimeline(responses[0].steps || [])
    setGraph(responses[1])
    setExplanation(responses[2].explanation)
    setAudit(responses[3].entries || [])
    setRisk(responses[4].risk)
    setRecommendation(responses[5])
    await refreshMetrics()
  }

  useEffect(() => {
    if (hasLoadedCase.current) return
    hasLoadedCase.current = true

    async function bootstrap() {
      try {
        const catalog = await fetchJson(`${API}/assurance/scenarios`)
        const casesList = (catalog.scenarios || [])
          .filter(s => s.expects_violation)
          .map((s, i) => {
            const isOld = i % 8 === 0;
            const created_at = new Date(Date.now() - (isOld ? 26 * 60 * 60 * 1000 : i * 3600000)).toISOString();
            const severity = i % 4 === 0 ? 'CRITICAL' : (i % 3 === 0 ? 'HIGH' : (i % 2 === 0 ? 'MEDIUM' : 'NORMAL'));
            return { name: s.name, severity, created_at, isOld };
          })
          .sort((a, b) => {
             if (a.isOld && !b.isOld) return -1;
             if (!a.isOld && b.isOld) return 1;
             const sev = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, NORMAL: 1 };
             return sev[b.severity] - sev[a.severity];
          });
        
        setPendingCases(casesList)
        if (casesList.length > 0) {
          await loadCase(casesList[0].name)
        }
      } catch (loadError) { setError(`API unavailable. Start FastAPI on port 8000. ${loadError.message}`) } finally { setLoading(false) }
    }
    bootstrap()
  }, [])

  async function selectScenario(name) {
    if (name === scenarioName) return;
    setLoading(true)
    setError('')
    setDrawerOpen(false)
    try { await loadCase(name) } catch (loadError) { setError(loadError.message) } finally { setLoading(false) }
  }

  async function approveAction() {
    if (!caseData || acting || caseData.violation_type === 'NO_VIOLATION') return
    setActing(true)
    try {
      const endpoint = caseData.recommended_action === 'REFUND_DUPLICATE' 
        ? `${API}/assurance/cases/${caseData.case_id}/actions/refund` 
        : `${API}/assurance/cases/${caseData.case_id}/approve`;
      const result = await fetchJson(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) })
      setCaseData(result.case)
      await refreshMetrics()
      const updatedAudit = await fetchJson(`${API}/assurance/cases/${result.case.case_id}/audit`)
      setAudit(updatedAudit.entries || [])
      setTimeline((await fetchJson(`${API}/assurance/cases/${result.case.case_id}/timeline`)).steps || [])
    } catch (actionError) { setError(actionError.message) } finally { setActing(false) }
  }

  async function submitClassification(e) {
    e.preventDefault()
    setActing(true)
    try {
      const result = await fetchJson(`${API}/assurance/cases/${caseData.case_id}/classify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(classification)
      })
      setClassifyMode(false)
      setCaseData(result.case)
      await refreshMetrics()
    } catch (actionError) { setError(actionError.message) } finally { setActing(false) }
  }

  const [customCasePayload, setCustomCasePayload] = useState('{\n  "name": "Duplicate collection — late authorization",\n  "amount_inr": 25000,\n  "order_id": "ord_demo_custom",\n  "events": [\n    {"event_type": "payment.created",    "payment_id": "pay_A", "amount": 2500000, "timestamp": "2026-09-02T10:00:00Z", "source": "gateway"},\n    {"event_type": "payment.timeout",    "payment_id": "pay_A",                      "timestamp": "2026-09-02T10:00:05Z", "source": "gateway"},\n    {"event_type": "agent.retry_initiated", "payment_id": "pay_A",                  "timestamp": "2026-09-02T10:00:30Z", "source": "agent"},\n    {"event_type": "payment.created",    "payment_id": "pay_B", "amount": 2500000, "timestamp": "2026-09-02T10:00:34Z", "source": "agent"},\n    {"event_type": "payment.authorized", "payment_id": "pay_B", "amount": 2500000, "timestamp": "2026-09-02T10:00:36Z", "source": "bank"},\n    {"event_type": "payment.captured",   "payment_id": "pay_B", "amount": 2500000, "timestamp": "2026-09-02T10:00:37Z", "source": "gateway"},\n    {"event_type": "payment.authorized", "payment_id": "pay_A", "amount": 2500000, "timestamp": "2026-09-02T10:04:12Z", "source": "bank"},\n    {"event_type": "payment.captured",   "payment_id": "pay_A", "amount": 2500000, "timestamp": "2026-09-02T10:04:13Z", "source": "gateway"}\n  ]\n}')

  async function submitCustomCase(e) {
    e.preventDefault()
    setActing(true)
    setError('')
    let payload
    try {
      payload = JSON.parse(customCasePayload)
    } catch (parseErr) {
      setError(`Invalid JSON: ${parseErr.message}`)
      setActing(false)
      return
    }
    try {
      const result = await fetchJson(`${API}/assurance/cases`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      setAddCaseDrawerOpen(false)
      
      const newCase = result.cases && result.cases.length > 0 ? result.cases[0] : { case_id: 'C-NO-ISSUE', status: 'ASSURED', severity: 'NORMAL', financial_exposure: 0, violation_type: 'NO_VIOLATION', workflow: 'VERIFIED' }
      setScenarioName('custom_case')
      setLeftView('graph')
      setCaseData(newCase)
      
      if (newCase.case_id !== 'C-NO-ISSUE') {
         setPendingCases(prev => [{ name: payload.name || newCase.case_id, severity: newCase.severity || 'HIGH', created_at: new Date().toISOString(), isOld: false, isCustom: true }, ...prev])
      }
      
      if (newCase.case_id === 'C-NO-ISSUE') {
         setTimeline([])
         setGraph({ nodes: [], edges: [] })
         setExplanation(null)
         setAudit([])
         setRisk(null)
         setRecommendation(null)
         return
      }
      
      const responses = await Promise.all(['timeline', 'graph', 'explanation', 'audit', 'risk', 'recommendation'].map((resource) => fetchJson(`${API}/assurance/cases/${newCase.case_id}/${resource}`)))
      setTimeline(responses[0].steps || [])
      setGraph(responses[1])
      setExplanation(responses[2].explanation)
      setAudit(responses[3].entries || [])
      setRisk(responses[4].risk)
      setRecommendation(responses[5])
      await refreshMetrics()
      
    } catch (err) {
      setError(`Failed to submit case: ${err.message}`)
    } finally {
      setActing(false)
    }
  }

  async function loadLearningStatus() {
    try {
      const result = await fetchJson(`${API}/assurance/learning/status`)
      setLearningStatus(result)
    } catch (err) {
      setError(`Failed to load learning status: ${err.message}`)
    }
  }

  async function triggerTraining() {
    setActing(true)
    setError('')
    try {
      await fetchJson(`${API}/assurance/learning/train`, { method: 'POST' })
      await loadLearningStatus()
    } catch (err) {
      setError(`Failed to train model: ${err.message}`)
    } finally {
      setActing(false)
    }
  }

  async function triggerPromotion(version) {
    setActing(true)
    setError('')
    try {
      await fetchJson(`${API}/assurance/learning/models/${version}/promote`, { method: 'POST' })
      await loadLearningStatus()
    } catch (err) {
      setError(`Failed to promote model: ${err.message}`)
    } finally {
      setActing(false)
    }
  }

  const rawFlowNodes = (graph.nodes || []).map((node) => ({ id: node.id, position: { x: 0, y: 0 }, data: { label: <GraphNode node={node} /> }, style: { background: node.is_violation_root ? 'rgba(244, 185, 66, .22)' : '#102326', color: '#eff8f2', border: node.is_violation_root ? '2px solid #75c99b' : '1px solid #294b50', borderRadius: 7, padding: 12, width: 224, boxShadow: node.is_violation_root ? '0 0 22px rgba(244, 185, 66, .12)' : 'none' } }))
  const flowEdges = (graph.edges || []).map((edge) => ({ ...edge, type: 'smoothstep', animated: edge.relation === 'triggered' || edge.relation === 'resolved', style: { stroke: relationColor(edge.relation), strokeWidth: edge.relation === 'resolved' ? 2.5 : 2 }, labelStyle: { fill: relationColor(edge.relation), fontSize: 10, fontFamily: 'DM Mono' }, labelBgStyle: { fill: '#102326', fillOpacity: .92, stroke: relationColor(edge.relation), strokeWidth: 1 }, labelBgPadding: [6, 3], labelBgBorderRadius: 3 }))
  
  const { nodes: flowNodes } = getLayoutedElements(rawFlowNodes, flowEdges)
  
  if (loading) return <div className="loading"><Activity size={18} /> Reconstructing financial outcome...</div>

  const isAssured = caseData?.status === 'ASSURED';
  const isUnknown = caseData?.pattern_status === 'UNKNOWN';
  const isNoViolation = caseData?.violation_type === 'NO_VIOLATION';
  const isMatched = caseData?.pattern_status === 'MATCHED';
  
  return <main className="shell">
    <header className="command-bar">
      <div className="command-brand"><span className="brand-mark"><ShieldCheck size={17} /></span><span>ASSURANCE</span></div>
      
      <button className="cases-drawer-btn" onClick={() => setDrawerOpen(true)}>
        <Menu size={15} /> CASES <span className="badge">{pendingCases.length} PENDING</span>
      </button>

      <button className="cases-drawer-btn add-case-btn" onClick={() => setAddCaseDrawerOpen(true)}>
        + ADD CASE
      </button>

      <button className="cases-drawer-btn learning-btn" onClick={() => { setLearningDrawerOpen(true); loadLearningStatus(); }}>
        <Sparkles size={15} /> LEARNING
      </button>

      <div className="command-live"><span className="live-dot" /> LIVE <span className="divider" /> {(caseData?.order_id || 'ord_hero').toUpperCase()}</div>
    </header>

    <div className={`drawer-overlay ${drawerOpen || addCaseDrawerOpen || learningDrawerOpen ? 'open' : ''}`} onClick={() => { setDrawerOpen(false); setAddCaseDrawerOpen(false); setLearningDrawerOpen(false); }}></div>
    
    <aside className={`cases-drawer ${learningDrawerOpen ? 'open' : ''} learning-drawer`}>
      <div className="drawer-header">
        <strong>LEARNING (STEP 3)</strong>
        <button onClick={() => setLearningDrawerOpen(false)}><X size={18} /></button>
      </div>
      <div className="drawer-content" style={{ padding: '20px' }}>
        {learningStatus ? (
          <>
            <div className="learning-stats">
              <div className="stat">
                <span className="label">VERIFIED OUTCOMES</span>
                <span className="value">{learningStatus.verified_outcomes}</span>
              </div>
              <div className="stat">
                <span className="label">VERIFIED PATTERNS</span>
                <span className="value">{learningStatus.verified_patterns}</span>
              </div>
              <div className="stat">
                <span className="label">ML TRAINING EXAMPLES</span>
                <span className="value">{learningStatus.ml_training_examples}</span>
              </div>
            </div>
            
            <div className="model-status">
              <span className="label">MODEL STATUS</span>
              <span className={`status-badge ${learningStatus.status === 'READY' ? 'ready' : 'insufficient'}`}>
                {learningStatus.status}
              </span>
            </div>

            {learningStatus.status === 'READY' && (
              <button className="primary-action" onClick={triggerTraining} disabled={acting} style={{ width: '100%', marginTop: '20px' }}>
                {acting ? 'TRAINING...' : '[TRAIN NEW MODEL]'}
              </button>
            )}

            {learningStatus.pending_model && (
              <div className="learning-candidate-box" style={{ marginTop: '20px', padding: '15px', background: 'rgba(255,255,255,0.05)', borderRadius: '6px' }}>
                <div style={{ marginBottom: '10px', fontWeight: 'bold' }}>CANDIDATE MODEL</div>
                <div style={{ fontSize: '11px', marginBottom: '5px' }}>VERSION: {learningStatus.pending_model.version}</div>
                <div style={{ fontSize: '11px', marginBottom: '5px', color: learningStatus.pending_model.status === 'VALIDATED' ? '#75c99b' : '#ff7a7a' }}>STATUS: {learningStatus.pending_model.status}</div>
                <div style={{ fontSize: '11px', marginBottom: '10px' }}>
                  F1: {(learningStatus.pending_model.f1).toFixed(2)} | 
                  Prec: {(learningStatus.pending_model.precision).toFixed(2)} | 
                  Rec: {(learningStatus.pending_model.recall).toFixed(2)}
                </div>
                
                {learningStatus.pending_model.status === 'VALIDATED' && (
                  <button className="primary-action" onClick={() => triggerPromotion(learningStatus.pending_model.version)} disabled={acting} style={{ width: '100%' }}>
                    {acting ? 'PROMOTING...' : '[PROMOTE TO ACTIVE]'}
                  </button>
                )}
              </div>
            )}
            
            {learningStatus.external_model && (
              <div className="learning-candidate-box" style={{ marginTop: '20px', padding: '15px', background: 'rgba(30,30,40,0.4)', border: '1px solid #4a4a6a', borderRadius: '6px' }}>
                <div style={{ marginBottom: '10px', fontWeight: 'bold', color: '#a5a5ff' }}>EXTERNAL INTELLIGENCE</div>
                <div style={{ fontSize: '11px', marginBottom: '5px' }}>DATASETS: PaySim, IEEE-CIS</div>
                <div style={{ fontSize: '11px', marginBottom: '5px' }}>VERSION: {learningStatus.external_model.version}</div>
                <div style={{ fontSize: '11px', marginBottom: '5px', color: '#ffb347' }}>STATUS: {learningStatus.external_model.status}</div>
                <div style={{ fontSize: '10px', color: '#888', marginTop: '10px' }}>
                  External behavioral training occurs offline via Notebooks. Assurance relies on the resulting model for purely advisory signals.
                </div>
              </div>
            )}
          </>
        ) : (
          <div>Loading status...</div>
        )}
      </div>
    </aside>

    <aside className={`cases-drawer ${drawerOpen ? 'open' : ''}`}>
      <div className="drawer-header">
        <strong>PENDING CASES</strong>
        <button onClick={() => setDrawerOpen(false)}><X size={18} /></button>
      </div>
      <div className="drawer-content">
        {pendingCases.map((scen) => (
          <button 
            key={scen.name} 
            className={`drawer-case-item ${scen.name === scenarioName ? 'active' : ''}`}
            onClick={() => selectScenario(scen.name)}
          >
             <div className="drawer-case-top">
                <span className={`drawer-sev sev-${scen.severity.toLowerCase()}`}>{scen.severity}</span>
                {scen.isOld && <span className="drawer-time-alert"><Clock size={11}/> &gt; 24H</span>}
             </div>
             <strong>{title(scen.name)}</strong>
          </button>
        ))}
      </div>
    </aside>

    <aside className={`cases-drawer ${addCaseDrawerOpen ? 'open' : ''}`} style={{ width: '500px' }}>
      <div className="drawer-header">
        <strong>ADD CUSTOM CASE</strong>
        <button onClick={() => setAddCaseDrawerOpen(false)}><X size={18} /></button>
      </div>
      <div className="drawer-content" style={{ padding: '20px' }}>
        <p className="muted-text" style={{ marginBottom: '15px' }}>Paste a JSON event stream to introduce a new, unseen pattern into the Assurance Engine.</p>
        <form onSubmit={submitCustomCase} style={{ display: 'flex', flexDirection: 'column', gap: '15px', height: '100%' }}>
          <textarea 
            className="json-textarea"
            value={customCasePayload}
            onChange={(e) => setCustomCasePayload(e.target.value)}
            style={{ flex: 1, minHeight: '300px', backgroundColor: '#0a1618', color: '#75c99b', border: '1px solid #294b50', borderRadius: '4px', padding: '10px', fontFamily: 'monospace', fontSize: '12px', resize: 'vertical' }}
          />
          <div className="form-actions" style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
            <button type="button" onClick={() => setAddCaseDrawerOpen(false)} style={{ background: 'transparent', color: '#888', border: 'none', cursor: 'pointer' }}>Cancel</button>
            <button type="submit" className="primary-action-btn" disabled={acting}>
              {acting ? 'Analyzing...' : 'Analyze Pattern'} <ArrowUpRight size={17} />
            </button>
          </div>
        </form>
      </div>
    </aside>

    <section className="workspace">
      {error && <div className="error"><CircleAlert size={16} /> {error}</div>}
      
      <div className="case-header-compact">
        <div className="header-left">
          <div className="case-kicker">
            <span className={`status status-${(caseData?.status || 'OPEN').toLowerCase()}`}>{caseData?.status || 'OPEN'}</span>
            <span className="severity">{caseData?.severity || 'NORMAL'}</span>
          </div>
          <h2>{isNoViolation ? 'NO DETERMINISTIC VIOLATION' : (isUnknown ? 'UNKNOWN PATTERN DETECTED' : title(caseData?.violation_type))}</h2>
        </div>
        <div className="header-metrics">
          <div><span>EXPOSURE</span><strong>{money(caseData?.financial_exposure)}</strong></div>
          <div><span>CONFIDENCE</span><strong>{Math.round((caseData?.confidence || 0) * 100)}%</strong></div>
          <div><span>WORKFLOW</span><strong>{(caseData?.workflow || 'Unknown').toUpperCase()}</strong></div>
          <div><span>CASE ID</span><strong>{caseData?.case_id}</strong></div>
        </div>
      </div>

      <div className="workspace-grid">
        <div className="workspace-left">
          {isNoViolation ? (
             <div className="no-violation-msg">
                <ShieldCheck size={40} />
                <h3>NO DETERMINISTIC VIOLATION</h3>
                <p>No supported financial invariant was breached by this event sequence.</p>
             </div>
          ) : (
            <div className="panel left-panel-container">
               <div className="panel-tabs">
                  <button className={`panel-tab ${leftView === 'graph' ? 'active' : ''}`} onClick={() => setLeftView('graph')}>CAUSAL GRAPH</button>
                  <button className={`panel-tab ${leftView === 'timeline' ? 'active' : ''}`} onClick={() => setLeftView('timeline')}>EVIDENCE TIMELINE <span className="tab-count">{timeline.length}</span></button>
                  <button className={`panel-tab ${leftView === 'audit' ? 'active' : ''}`} onClick={() => setLeftView('audit')}>AUDIT TRAIL <span className="tab-count">{audit.length}</span></button>
               </div>
               <div className="left-panel-content">
                 {leftView === 'graph' && <GraphView caseData={caseData} graph={graph} nodes={flowNodes} edges={flowEdges} />}
                 {leftView === 'timeline' && <Timeline steps={timeline} detailed />}
                 {leftView === 'audit' && <AuditTrail entries={audit} />}
               </div>
            </div>
          )}
        </div>

        <div className="workspace-right explanation-panel">
          <div className="lifecycle-visual">
             <div className="lifecycle-stage done">DETECTED</div>
             <div className="lifecycle-line done"></div>
             <div className="lifecycle-stage done">INVESTIGATING</div>
             <div className="lifecycle-line done"></div>
             <div className={`lifecycle-stage ${isAssured ? 'done' : 'active'}`}>APPROVAL</div>
             <div className={`lifecycle-line ${isAssured ? 'done' : ''}`}></div>
             <div className={`lifecycle-stage ${isAssured ? 'done' : 'pending'}`}>RESOLVING</div>
             <div className={`lifecycle-line ${isAssured ? 'done' : ''}`}></div>
             <div className={`lifecycle-stage ${isAssured ? 'done' : 'pending'}`}>VERIFYING</div>
             <div className={`lifecycle-line ${isAssured ? 'done' : ''}`}></div>
             <div className={`lifecycle-stage ${isAssured ? 'done' : 'pending'}`}>ASSURED</div>
          </div>

          <div className="explanation-section">
            <span className="eyebrow">WHAT HAPPENED</span>
            <p className="explanation-text">{explanation?.summary || caseData?.violation_description || 'The event sequence was fully reconstructed.'}</p>
          </div>

          <div className="explanation-section">
            <span className="eyebrow">ROOT CAUSE</span>
            <p className="explanation-text">{explanation?.root_cause || 'The event evidence requires investigation.'}</p>
          </div>

          {!isNoViolation && (
            <div className="explanation-section">
              <span className="eyebrow">WHY ASSURANCE FLAGGED IT</span>
              <div className={`flag-reason ${isUnknown ? 'unknown-pattern' : 'deterministic'}`}>
                 {isUnknown ? <AlertTriangle size={15}/> : <ShieldCheck size={15}/>}
                 <span>{isUnknown ? 'Anomaly detected outside known invariants.' : 'Deterministic financial invariant violated.'}</span>
              </div>
              {!isUnknown && <p className="muted-text">{caseData?.causal_summary || 'A known rule was broken.'}</p>}
            </div>
          )}

          <div className="explanation-section">
            <span className="eyebrow">FINANCIAL IMPACT</span>
            {caseData?.exposure_details?.financially_applicable === false || caseData?.financial_exposure == null ? (
               <div className="impact-box"><p style={{margin: '10px 0', fontSize: '13px', color: '#888'}}>No monetary exposure established</p></div>
            ) : (
               <div className="impact-box">
                  <div className="impact-row"><span>Expected</span><strong>{caseData?.exposure_details?.expected_amount != null ? money(caseData.exposure_details.expected_amount) : money(caseData?.expected_state?.amount_inr * 100 || 0)}</strong></div>
                  <div className="impact-row"><span>Actual</span><strong>{caseData?.exposure_details?.actual_amount != null ? money(caseData.exposure_details.actual_amount) : money(caseData?.observed_state?.total_captured_inr * 100 || 0)}</strong></div>
                  <div className="impact-row highlight"><span>Exposure</span><strong>{caseData?.exposure_details?.gross_exposure != null ? money(caseData.exposure_details.gross_exposure) : money(caseData?.financial_exposure)}</strong></div>
               </div>
            )}
          </div>

          <div className="explanation-section ml-section">
            <span className="eyebrow">ML RISK & ANOMALY SCORE <Activity size={13}/></span>
            <div className="ml-box">
              <div className="score-main">
                <span className="label">Risk / Anomaly Score</span>
                <span className={`value ${caseData?.risk_assessment?.is_anomaly ? 'anomaly' : ''}`}>
                  {caseData?.risk_assessment?.risk_score != null 
                     ? `${Math.round(caseData.risk_assessment.risk_score * 100)}%` 
                     : 'ML signal unavailable'}
                </span>
              </div>
              <div className="score-sub">
                <span className="label">External Behavior</span>
                <span className="value">
                  {caseData?.risk_assessment?.external_behavior_signal != null 
                     ? `${Math.round(caseData.risk_assessment.external_behavior_signal * 100)}%` 
                     : 'ML signal unavailable'}
                </span>
              </div>
            </div>
          </div>

          {recommendation && (
            <div className="explanation-section ml-section">
              <span className="eyebrow">HISTORICAL OUTCOMES <Clock size={13}/></span>
              <div className="ml-box">
                <div><span>Similar Verified Cases</span><strong>{recommendation.similar_cases}</strong></div>
                {recommendation.successful_cases > 0 ? (
                  <div><span>Success Rate</span><strong>{Math.round(recommendation.success_rate * 100)}%</strong></div>
                ) : (
                  <div><span>Confidence</span><strong>N/A</strong></div>
                )}
              </div>
              <p className="muted-text">{recommendation.reason}</p>
            </div>
          )}

          <div className="explanation-section action-section">
            <span className="eyebrow">WHAT SHOULD HAPPEN</span>
            
            {isUnknown ? (
              classifyMode ? (
                <form className="classification-form" onSubmit={submitClassification}>
                  <div className="form-group">
                    <label>Violation Type</label>
                    <input value={classification.violation_type} onChange={e => setClassification({...classification, violation_type: e.target.value})} required />
                  </div>
                  <div className="form-group">
                    <label>Reason</label>
                    <input value={classification.reason} onChange={e => setClassification({...classification, reason: e.target.value})} required />
                  </div>
                  <div className="form-group">
                    <label>Recommended Action</label>
                    <input value={classification.recommended_action} onChange={e => setClassification({...classification, recommended_action: e.target.value})} required />
                  </div>
                  <div className="form-actions">
                    <button type="button" onClick={() => setClassifyMode(false)}>Cancel</button>
                    <button type="submit" className="primary-action-btn" disabled={acting}>{acting ? 'Saving...' : 'Save Classification'}</button>
                  </div>
                </form>
              ) : (
                <>
                  <p className="recommended-action-text" style={{whiteSpace: 'normal', wordWrap: 'break-word'}}>INVESTIGATE (Unknown Pattern)</p>
                  <button className="primary-action-btn" onClick={() => setClassifyMode(true)}>
                    Classify Case <ArrowUpRight size={17} />
                  </button>
                </>
              )
            ) : (
              <>
                <p className="recommended-action-text" style={{whiteSpace: 'normal', wordWrap: 'break-word'}}>{isAssured || isNoViolation ? 'Case resolved successfully.' : (caseData?.recommended_action ? title(caseData.recommended_action) : 'NO ACTION')}</p>
                {!isAssured && !isNoViolation && caseData?.recommended_action && caseData.recommended_action !== 'NO_ACTION' && (
                  <button className="primary-action-btn" onClick={approveAction} disabled={acting}>
                    {acting ? 'Verifying...' : 'Approve Action'} <ArrowUpRight size={17} />
                  </button>
                )}
                {(isAssured || isNoViolation) && (
                   <div className="assured-badge"><Check size={16}/> OUTCOME VERIFIED</div>
                )}
              </>
            )}
          </div>

        </div>
      </div>
    </section>
  </main>
}

function relationColor(relation) { return relation === 'triggered' ? '#55d66f' : relation === 'resolved' ? '#f4b942' : relation === 'contributes to' ? '#ff786c' : '#55a9e8' }
function GraphNode({ node }) {
  const label = node.event_type === 'payment.timeout' ? 'OUTCOME UNCERTAIN' : node.event_type === 'agent.retry_initiated' ? 'AUTONOMOUS ACTION' : node.event_type === 'payment.authorized' && node.payment_id === 'pay_A' ? 'LATE AUTHORIZATION' : node.event_type === 'payment.captured' ? 'FUNDS COLLECTED' : ''
  return <div className="graph-node"><time>{time(node.timestamp)}</time><strong>{node.event_type}</strong><span>{node.payment_id || 'order event'}</span>{label && <em className={`node-badge badge-${node.event_type.split('.')[1]}`}>{label}</em>}</div>
}
function GraphView({ caseData, graph, nodes, edges, timeline }) {
  const triggered = edges.filter((edge) => edge.relation === 'triggered').length
  const preceded = edges.filter((edge) => edge.relation === 'preceded').length
  const resolved = edges.filter((edge) => edge.relation === 'resolved').length
  const workflow = title(caseData?.workflow || 'financial')
  return <div className="graph-panel">
    <div className="graph-legend"><span>LEGEND:</span><i className="legend-triggered" /> triggered by <i className="legend-preceded" /> preceded by <i className="legend-resolved" /> resolved by <i className="legend-contributes" /> contributes to</div>
    <div className="graph-canvas">
      <div className="lane lane-a"><strong>{workflow.toUpperCase()} WORKFLOW</strong><span>{caseData?.order_id || 'Order stream'}</span></div>
      <div className="lane lane-b"><strong>{caseData?.violation_type === 'NO_VIOLATION' ? 'NO VIOLATION' : (caseData?.violation_type ? title(caseData.violation_type) : 'UNKNOWN PATTERN')}</strong><span>Detected outcome</span></div>
      <ReactFlow key={`${graph.nodes.length}-${graph.edges.length}`} nodes={nodes} edges={edges} fitView fitViewOptions={{ padding: .12 }} nodesDraggable={false} style={{ width: '100%', height: '100%' }}><Background color="#18383b" gap={24} /><Controls /></ReactFlow>
      <div className="graph-summary"><strong>SUMMARY</strong><span><b className="summary-green">{new Set((graph.nodes || []).map((node) => node.payment_id).filter(Boolean)).size}</b> Payments</span><span><b className="summary-mint">{graph.nodes.length}</b> Events</span><span><b className="summary-green">→ {triggered}</b> Triggered</span><span><b className="summary-blue">→ {preceded}</b> Preceded</span><span><b className="summary-amber">→ {resolved}</b> Resolved</span><span><b className="summary-red">→ {graph.nodes.filter((node) => node.is_violation_root).length}</b> Violations</span></div>
    </div>
  </div>
}

function Timeline({ steps, detailed = false }) { return <div className={`timeline ${detailed ? 'detailed' : ''}`}>{steps.map((step, index) => <div className="timeline-item" key={`${step.event_id || step.timestamp}-${index}`}><div className="timeline-time">{time(step.timestamp)}</div><div className="timeline-marker"><span /></div><div className="timeline-copy"><strong>{step.event_type}</strong><span>{step.description}</span>{step.payment_id && <em>{step.payment_id} {step.amount_inr ? `· ${money(step.amount_inr * 100)}` : ''}</em>}</div></div>)}</div> }
function AuditTrail({ entries }) { return <div className="audit-list">{entries.map((entry, index) => <div className="audit-entry" key={`${entry.event_id}-${index}`}><span>{time(entry.timestamp)}</span><div><strong>{entry.actor}</strong><p>{entry.description}</p><em>{entry.event_type} · {entry.event_id}</em></div></div>)}</div> }

export default App
