import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
// import { api } from '../api/client'; // Uncomment when backend is ready

export interface FieldProfilePayload {
  location: string;
  soilTexture: string;
  irrigationAccess: string;
  previousCrop: string;
  priorities: string[];
}

export default function FieldSetup() {
  const navigate = useNavigate();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [location, setLocation] = useState('');
  const [soilTexture, setSoilTexture] = useState('Sandy-loam');
  const [irrigationAccess, setIrrigationAccess] = useState('None (Rain-fed)');
  const [previousCrop, setPreviousCrop] = useState('Maize');
  const [priorities, setPriorities] = useState<string[]>(['Water conservation']);

  const handlePriorityChange = (priority: string) => {
    if (priorities.includes(priority)) {
      setPriorities(priorities.filter(p => p !== priority));
    } else {
      setPriorities([...priorities, priority]);
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!location.trim()) {
      setError('Please provide a location or coordinates.');
      return;
    }
    if (priorities.length === 0) {
      setError('Please select at least one priority.');
      return;
    }

    setIsLoading(true);
    try {
      // Mock API call
      await new Promise((resolve) => setTimeout(resolve, 800)); 
      console.log('Submitted:', { location, soilTexture, irrigationAccess, previousCrop, priorities });
      navigate('/comparison');
    } catch (err: any) {
      setError(err.message || 'Failed to submit.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="page-container">
      <div className="form-card">
        <div className="form-header">
          <h2>Field Profile</h2>
          <p>Provide your field details so NovaYield can analyze NASA data and generate rotation options.</p>
        </div>
        
        {error && <div style={{ color: '#b91c1c', marginBottom: '1rem', fontWeight: '500' }}>{error}</div>}

        <form onSubmit={handleSubmit} className="form-grid">
          
          <div className="form-group">
            <label htmlFor="location">Site Location (Required)</label>
            <input 
              id="location"
              type="text" 
              value={location} 
              onChange={(e) => setLocation(e.target.value)} 
              placeholder="e.g., Tamale, Ghana or 9.4008, -0.8393"
              className="form-input"
            />
          </div>

          <div className="form-group">
            <label htmlFor="soil">Soil Texture</label>
            <select id="soil" value={soilTexture} onChange={(e) => setSoilTexture(e.target.value)} className="form-select">
              <option value="Sandy">Sandy</option>
              <option value="Sandy-loam">Sandy-loam</option>
              <option value="Loam">Loam</option>
              <option value="Clay">Clay</option>
              <option value="Clay-loam">Clay-loam</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="irrigation">Irrigation Access</label>
            <select id="irrigation" value={irrigationAccess} onChange={(e) => setIrrigationAccess(e.target.value)} className="form-select">
              <option value="None (Rain-fed)">None (Rain-fed)</option>
              <option value="Partial">Partial / Supplemental</option>
              <option value="Full">Full Irrigation</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="crop">Previous Crop</label>
            <select id="crop" value={previousCrop} onChange={(e) => setPreviousCrop(e.target.value)} className="form-select">
              <option value="Maize">Maize</option>
              <option value="Cowpea">Cowpea</option>
              <option value="Groundnut">Groundnut</option>
              <option value="Cassava">Cassava</option>
              <option value="Sorghum">Sorghum</option>
              <option value="Soybean">Soybean</option>
            </select>
          </div>

          <div className="priorities-section">
            <div className="priorities-title">Farmer Priorities (Select all that apply)</div>
            <div className="checkbox-grid">
              {['Water conservation', 'Soil health', 'Labor availability', 'Yield stability'].map((priority) => (
                <label key={priority} className="checkbox-label">
                  <input 
                    type="checkbox" 
                    checked={priorities.includes(priority)}
                    onChange={() => handlePriorityChange(priority)}
                  />
                  {priority}
                </label>
              ))}
            </div>
          </div>

          <div className="form-actions">
            <button type="submit" disabled={isLoading} className="submit-btn">
              {isLoading ? 'Processing...' : 'Generate Options'}
            </button>
          </div>

        </form>
      </div>
    </div>
  );
}