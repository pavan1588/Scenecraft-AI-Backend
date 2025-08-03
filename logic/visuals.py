# logic/visuals.py

import seaborn as sns
import io
import base64
import numpy as np

def generate_base64_chart(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    base64_img = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return base64_img

def create_heatmap():
    data = np.random.rand(10, 10)
    fig, ax = plt.subplots()
    sns.heatmap(data, ax=ax, cmap="YlOrRd")
    ax.set_title("Scene Emotional Heatmap")
    return generate_base64_chart(fig)

def create_beat_curve():
    x = np.linspace(0, 1, 10)
    y = np.sin(2 * np.pi * x) + np.random.normal(0, 0.2, 10)
    fig, ax = plt.subplots()
    ax.plot(x, y, marker='o')
    ax.set_title("Beat Progression Curve")
    ax.set_xlabel("Scene Time")
    ax.set_ylabel("Emotional Intensity")
    return generate_base64_chart(fig)

def create_dialogue_vs_silence():
    labels = ["Dialogue", "Silence"]
    sizes = [70, 30]  # Dummy data
    fig, ax = plt.subplots()
    ax.pie(sizes, labels=labels, autopct='%1.1f%%', colors=['gold', 'grey'])
    ax.set_title("Dialogue vs Silence Ratio")
    return generate_base64_chart(fig)

def generate_all_visuals():
    return {
        "heatmap": create_heatmap(),
        "beat_curve": create_beat_curve(),
        "dialogue_silence": create_dialogue_vs_silence()
    }
