# What is needed to build the Android app and to try it without a phone: the Android SDK,
# Gradle, an emulator and a plain Android 15 and 13 for it. Nothing here ends up in the app.
# Build it with ..\..\android.ps1, which also runs it.
FROM ghcr.io/cirruslabs/android-sdk:35

# The emulator and its Android come from Google under the Android SDK licence, accepted here.
RUN yes | sdkmanager --licenses > /dev/null \
    && sdkmanager "emulator" "system-images;android-35;default;x86_64" > /dev/null \
    && echo no | avdmanager create avd --name regista --package "system-images;android-35;default;x86_64" --device pixel_6

ARG GRADLE=8.10.2
RUN curl -fsSL "https://services.gradle.org/distributions/gradle-${GRADLE}-bin.zip" -o /tmp/gradle.zip \
    && unzip -q /tmp/gradle.zip -d /opt && rm /tmp/gradle.zip && ln -s "/opt/gradle-${GRADLE}/bin/gradle" /usr/local/bin/gradle

# Android 13 too, the Android of the phone the app is mostly used on: android.ps1 phone 13 starts it
RUN sdkmanager "system-images;android-33;default;x86_64" > /dev/null \
    && echo no | avdmanager create avd --name regista13 --package "system-images;android-33;default;x86_64" --device pixel_6

ENV PATH="${PATH}:/opt/android-sdk-linux/emulator"
WORKDIR /work
