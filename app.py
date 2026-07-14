import os
from flask import Flask, render_template

app = Flask(__name__, template_folder = 'templates', static_folder='static', static_url_path='/static')
app.secret_key = os.getenv('Flask_Secret_Key')

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/home')
def index():
    return render_template('index.html')

@app.route('/browse')
def browse():
    return render_template('browse.html')

@app.route('/signup')

def signup():
    return render_template('signup.html')


if __name__ == "__main__":
    app.run(debug = True)