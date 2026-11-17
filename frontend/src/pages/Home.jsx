import Header from "../components/Header.jsx";

export default function Home() {
  return (
    <>
      <Header />
      <main>
        <section className="hero">
          <h2>May sumbong ka?</h2>
          <p>Every report rises until it is resolved. Barangay incident reporting for Iloilo City.</p>
        </section>
        <p>Choose how you are using eSumbong.</p>
        <div className="grid roles">
          <a href="#/resident">
            <div className="card">
              <h2>Resident</h2>
              <p>Report an incident in your purok and follow its status.</p>
            </div>
          </a>
          <a href="#/responder">
            <div className="card">
              <h2>Responder / Desk</h2>
              <p>Tanods, barangay captain, and the city desk: receive reports and update their status.</p>
            </div>
          </a>
        </div>
      </main>
    </>
  );
}
