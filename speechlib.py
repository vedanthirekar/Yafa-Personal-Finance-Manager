import speech_recognition as sr
 
# Initialize the recognizer 
r = sr.Recognizer() 
 
# Defined function for speech recognition
def getPhrase(path="audio.wav"):
    try:
       #Load the audio file
        audiofile = sr.AudioFile(path)

        with audiofile as source:
             
            # wait a full second to let the recognizer adjust the energy
            # threshold based on the surrounding noise level -- 0.2s was too
            # short to get a stable noise floor for short voice-memo clips
            r.adjust_for_ambient_noise(source, duration=1.0)

            # Creates a audio source out of the wav file
            audio2 = r.listen(source, phrase_time_limit=20)

            # Using google to recognize audio. This is the free, unofficial
            # Google Web Speech API (no API key, no confidence scores, no
            # domain adaptation) -- it's a real ceiling on transcription
            # quality that tuning alone can't fully overcome.
            MyText = r.recognize_google(audio2)
            MyText = MyText.lower()

            print("Did you say ",MyText)
            return str(MyText)
             
    except sr.RequestError as e:
        print("Could not request results; {0}".format(e))
         
    except sr.UnknownValueError:
        print("unknown error occurred")

