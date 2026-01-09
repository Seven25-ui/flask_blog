Flask Blog
A simple Flask-based blog application with user authentication, post management, and clean UI. Perfect for personal blogs, tutorials, or small projects.
Features
✅ User registration and login system
✅ Create, edit, and delete posts
✅ Post slugs for clean URLs (/post/<slug>)
✅ Dashboard for managing posts
✅ Author and timestamp tracking for each post
✅ SQLite database (stored in instance/blog.db)
✅ Fully customizable templates (templates/) and static files (static/)
Project Structure
Copy code

flask_blog/
│
├─ app.py              # Main Flask app
├─ README.md           # Project documentation
├─ clean_git.sh        # Script to clean & compress Git history
├─ bfg.jar             # Optional BFG Repo Cleaner jar
├─ instance/           # Database and instance folder (ignored in git)
├─ venv/               # Virtual environment (ignored in git)
├─ __pycache__/        # Python cache
├─ static/             # CSS, JS, images
└─ templates/          # HTML templates
Setup & Installation
Clone the repository:
Copy code
Bash
git clone https://github.com/Seven25-ui/flask_blog.git
cd flask_blog
Create a virtual environment and activate it:
Copy code
Bash
python3 -m venv venv
source venv/bin/activate   # Linux / Termux / macOS
venv\Scripts\activate      # Windows
Install dependencies:
Copy code
Bash
pip install -r requirements.txt
(If requirements.txt is missing, just install Flask & SQLAlchemy manually)
Copy code
Bash
pip install flask flask_sqlalchemy werkzeug
Run the app:
Copy code
Bash
python app.py
Open in browser:
Go to http://127.0.0.1:5000
First time, register a user
Login to access the dashboard and create posts
Git Cleanup Script
You can run clean_git.sh to compress Git history and force-push changes:
Copy code
Bash
./clean_git.sh
This is useful if your repo has too many large files or you just added .gitignore.
Contribution
Fork the repo
Make changes / improvements
Create a pull request
License
MIT License — free to use and modify.
