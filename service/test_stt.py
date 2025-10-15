import speech_recognition as sr

recognizer = sr.Recognizer()
with sr.Microphone() as source:
    print("말씀하세요:)")
    recognizer.adjust_for_ambient_noise(source)
    audio = recognizer.listen(source)

try:
    result = recognizer.recognize_google(audio, language='ko-KR')
    print("인식 결과:", result)
except sr.UnknownValueError:
    print("음성을 이해하지 못함")
except sr.RequestError as e:
    print(f"API 오류: {e}")
