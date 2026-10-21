import './App.css'

function App() {
  return (
    <main className="app-shell">
      <header className="site-header">
        <a className="wordmark" href="/" aria-label="Nova Yield home">
          <span className="wordmark-mark" aria-hidden="true">N</span>
          <span>Nova Yield</span>
        </a>
        <span className="project-label">NASA Space Apps Challenge</span>
      </header>

      <section className="welcome" aria-labelledby="welcome-title">
        <p className="eyebrow">Farm decision support</p>
        <h1 id="welcome-title">A clearer view of crop rotation choices.</h1>
        <p className="welcome-copy">
          Nova Yield brings farm information and environmental context together to help
          farmers explore rotation options and understand their trade-offs.
        </p>
        <p className="foundation-note">The application foundation is ready for future features.</p>
      </section>

      <footer className="site-footer">
        <span>Nova Yield MVP</span>
        <span className="api-status">API integration ready for future work</span>
      </footer>
    </main>
  )
}

export default App
